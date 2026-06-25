# ruff: noqa
import re
import json
import logging
from typing import Any, Optional
from pydantic import BaseModel, Field

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import AgentTool, McpToolset
from google.adk.workflow import Workflow, Edge, START, node, DEFAULT_ROUTE
from google.adk.events import Event, RequestInput
from google.adk.agents.context import Context
from google.genai import types
from mcp import StdioServerParameters

from app.config import config

# Set up logging for audit log
logging.basicConfig(level=logging.INFO)
audit_logger = logging.getLogger("elderly_care_audit")

# Care state definition
class CareState(BaseModel):
    query: str = ""
    scrubbed_query: str = ""
    patient_name: str = "John Doe"
    proposed_medication: str = ""
    proposed_appointment: str = ""
    approved_changes: str = ""
    audit_log: list[str] = Field(default_factory=list)

# Initialize MCP toolsets for specialized agents
med_mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command="uv",
        args=["run", "app/mcp_server.py"],
    ),
    tool_filter=["get_medications", "add_medication"]
)

appt_mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command="uv",
        args=["run", "app/mcp_server.py"],
    ),
    tool_filter=["get_appointments", "add_appointment", "log_health_checkin"]
)

# Medication Sub-Agent
medication_agent = Agent(
    name="medication_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are the Medication Safety Sub-Agent. Your job is to check medication schedules, "
        "dosages, and safety protocols for elderly patients. Use the tools in your toolset to retrieve "
        "or add medication details. If asked to prescribe or add medication, check for conflicts, "
        "and if safe, return a clear list of what medication to add."
    ),
    tools=[med_mcp_toolset],
    mode="chat",
)

# Appointment Sub-Agent
appointment_agent = Agent(
    name="appointment_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are the Appointment Coordination Sub-Agent. Your job is to coordinate doctor appointments, "
        "health checks, and calendars for elderly patients. Use the tools in your toolset to check existing "
        "appointments, schedule new ones, or log health check-ins. Check for scheduling conflicts and return "
        "clear, concise outcomes."
    ),
    tools=[appt_mcp_toolset],
    mode="chat",
)

# Care Coordinator Orchestrator
orchestrator = Agent(
    name="orchestrator",
    model=Gemini(model=config.model),
    instruction=(
        "You are the Care Coordinator Orchestrator. You help coordinate care for elderly patients. "
        "When the user makes a request, determine which sub-agent is appropriate and call its tool. "
        "If the user wants to add/update medication or schedule an appointment, call the tool first "
        "and then in your final response state: 'PROPOSAL: [describe the proposed change]' so the system "
        "can queue it for family review. If it is only a query, answer it directly without using the 'PROPOSAL' keyword."
    ),
    tools=[
        AgentTool(medication_agent),
        AgentTool(appointment_agent),
    ],
    mode="single_turn",
)

# Security checkpoint node
@node
def security_checkpoint(ctx: Context, node_input: str) -> Event:
    """PII Scrubbing and Prompt Injection detection."""
    # Initialize list if not present
    if not ctx.state.get("audit_log"):
        ctx.state["audit_log"] = []
    
    # Audit log entry
    audit_entry = {"event": "security_checkpoint_entry", "input": node_input}
    
    # 1. Prompt Injection Detection
    injection_keywords = ["ignore previous", "override config", "bypass", "system instructions", "developer mode"]
    detected_injection = any(kw in node_input.lower() for kw in injection_keywords)
    if detected_injection:
        audit_entry["status"] = "BLOCKED"
        audit_entry["reason"] = "Prompt injection keywords detected"
        audit_logger.warning(json.dumps(audit_entry))
        ctx.state["audit_log"] = ctx.state["audit_log"] + [json.dumps(audit_entry)]
        return Event(
            output="Security check failed: Unauthorized prompt modification keywords detected.",
            route="security_event"
        )
    
    # 2. PII Scrubbing (Regex for phone numbers and SSN)
    phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
    ssn_pattern = r'\b\d{3}-\d{2}-\d{4}\b'
    scrubbed = re.sub(phone_pattern, "[PHONE REDACTED]", node_input)
    scrubbed = re.sub(ssn_pattern, "[SSN REDACTED]", scrubbed)
    
    # Domain specific rule: check for toxic drugs / medical safety keywords
    toxic_keywords = ["morphine", "fentanyl", "oxycodone"]
    for word in toxic_keywords:
        if word in scrubbed.lower():
            audit_entry["status"] = "WARNING"
            audit_entry["reason"] = f"Sensitive medical keyword detected: {word}"
            audit_logger.warning(json.dumps(audit_entry))
            ctx.state["audit_log"] = ctx.state["audit_log"] + [json.dumps(audit_entry)]
            # We don't block it, but we log a warning.
    
    # Save to state
    ctx.state["query"] = node_input
    ctx.state["scrubbed_query"] = scrubbed
    
    audit_entry["status"] = "PASSED"
    audit_entry["scrubbed_output"] = scrubbed
    ctx.state["audit_log"] = ctx.state["audit_log"] + [json.dumps(audit_entry)]
    audit_logger.info(json.dumps(audit_entry))
    
    return Event(output=scrubbed, route="passed")

# Routing node that analyzes orchestrator response
@node
def routing_node(ctx: Context, node_input: str) -> Event:
    """Routes based on whether the orchestrator proposed a change."""
    if "PROPOSAL:" in node_input:
        proposal = node_input.split("PROPOSAL:")[1].strip()
        # Parse proposed change type
        if "medication" in proposal.lower() or "prescribe" in proposal.lower() or "dose" in proposal.lower():
            ctx.state["proposed_medication"] = proposal
        else:
            ctx.state["proposed_appointment"] = proposal
            
        return Event(output=node_input, route="approval_needed")
    
    return Event(output=node_input, route="direct")

# Human approval node
@node
def human_approval(ctx: Context, node_input: str) -> Event:
    """Pauses for human approval using RequestInput."""
    proposal = ctx.state.get("proposed_medication") or ctx.state.get("proposed_appointment") or "Proposed caregiving updates"
    
    # Check if we have the resume response
    approval_response = ctx.resume_inputs.get("hitl_approval")
    
    if approval_response is not None:
        response_str = str(approval_response).strip().lower()
        audit_entry = {
            "event": "human_approval_response",
            "proposal": proposal,
            "response": response_str
        }
        
        if response_str in ["yes", "approve", "y"]:
            ctx.state["approved_changes"] = proposal
            ctx.state["proposed_medication"] = ""
            ctx.state["proposed_appointment"] = ""
            audit_entry["status"] = "APPROVED"
            ctx.state["audit_log"] = ctx.state["audit_log"] + [json.dumps(audit_entry)]
            audit_logger.info(json.dumps(audit_entry))
            return Event(output=f"Change approved: {proposal}. System updated.", route="approved")
        else:
            ctx.state["proposed_medication"] = ""
            ctx.state["proposed_appointment"] = ""
            audit_entry["status"] = "REJECTED"
            ctx.state["audit_log"] = ctx.state["audit_log"] + [json.dumps(audit_entry)]
            audit_logger.info(json.dumps(audit_entry))
            return Event(output=f"Change rejected by family: {proposal}.", route="denied")
            
    # Yield RequestInput to pause and ask the user
    yield RequestInput(
        interrupt_id="hitl_approval",
        message=f"Family Approval Required:\n\n{proposal}\n\nDo you approve this change? (yes/no)"
    )

# Final output formatter node
@node
def final_output(ctx: Context, node_input: str) -> str:
    """Formats and returns the final response."""
    return node_input

# Workflow definition
root_agent = Workflow(
    name="elderly_care_workflow",
    description="Workflow to coordinate elderly caregiving with safety checks and HITL approval",
    state_schema=CareState,
    edges=[
        Edge(from_node=START, to_node=security_checkpoint),
        Edge(from_node=security_checkpoint, to_node=orchestrator, route="passed"),
        Edge(from_node=security_checkpoint, to_node=final_output, route="security_event"),
        Edge(from_node=orchestrator, to_node=routing_node),
        Edge(from_node=routing_node, to_node=human_approval, route="approval_needed"),
        Edge(from_node=routing_node, to_node=final_output, route="direct"),
        Edge(from_node=human_approval, to_node=final_output),
    ]
)

app = App(
    root_agent=root_agent,
    name="app",
)

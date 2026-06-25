import os
import json
from datetime import datetime
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP
mcp = FastMCP("Elderly Care Helper")

DATA_FILE = os.path.join(os.path.dirname(__file__), "care_data.json")

def load_data():
    if not os.path.exists(DATA_FILE):
        default_data = {
            "medications": {
                "John Doe": [
                    {"med_name": "Donepezil", "dosage": "10mg", "schedule": "morning"},
                    {"med_name": "Lisinopril", "dosage": "20mg", "schedule": "evening"}
                ]
            },
            "appointments": {
                "John Doe": [
                    {"doctor": "Dr. Smith (Cardiologist)", "datetime_str": "2026-07-10 10:00 AM", "purpose": "Routine cardiology follow-up"}
                ]
            },
            "checkins": {
                "John Doe": [
                    {"timestamp": "2026-06-25 08:00 AM", "vital_stats": "BP 120/80, HR 72, Temp 98.6 F", "notes": "Feeling well, walked in the garden."}
                ]
            }
        }
        with open(DATA_FILE, "w") as f:
            json.dump(default_data, f, indent=4)
        return default_data
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except Exception:
        # Fallback in case of corruption
        return {"medications": {}, "appointments": {}, "checkins": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

@mcp.tool()
def get_medications(patient_name: str) -> str:
    """Get the current medications and schedules for a patient.
    
    Args:
        patient_name: The name of the patient.
    """
    data = load_data()
    meds = data.get("medications", {}).get(patient_name, [])
    if not meds:
        return f"No medications found for {patient_name}."
    
    result = f"Medications for {patient_name}:\n"
    for m in meds:
        result += f"- {m['med_name']} ({m['dosage']}), Schedule: {m['schedule']}\n"
    return result

@mcp.tool()
def add_medication(patient_name: str, med_name: str, dosage: str, schedule: str) -> str:
    """Add a new medication entry for a patient.
    
    Args:
        patient_name: The name of the patient.
        med_name: The name of the medication.
        dosage: The dosage (e.g. '10mg').
        schedule: The schedule (e.g. 'morning', 'twice daily').
    """
    data = load_data()
    meds_dict = data.setdefault("medications", {})
    patient_meds = meds_dict.setdefault(patient_name, [])
    
    # Check for duplicate
    for m in patient_meds:
        if m["med_name"].lower() == med_name.lower():
            return f"{med_name} is already listed for {patient_name}."
            
    patient_meds.append({
        "med_name": med_name,
        "dosage": dosage,
        "schedule": schedule
    })
    save_data(data)
    return f"Successfully added {med_name} {dosage} ({schedule}) for {patient_name}."

@mcp.tool()
def get_appointments(patient_name: str) -> str:
    """Get upcoming medical appointments for a patient.
    
    Args:
        patient_name: The name of the patient.
    """
    data = load_data()
    apps = data.get("appointments", {}).get(patient_name, [])
    if not apps:
        return f"No upcoming appointments found for {patient_name}."
    
    result = f"Upcoming appointments for {patient_name}:\n"
    for a in apps:
        result += f"- {a['doctor']} on {a['datetime_str']} (Purpose: {a['purpose']})\n"
    return result

@mcp.tool()
def add_appointment(patient_name: str, doctor: str, datetime_str: str, purpose: str) -> str:
    """Schedule a new medical appointment for a patient.
    
    Args:
        patient_name: The name of the patient.
        doctor: Doctor's name and specialty.
        datetime_str: Date and time of the appointment (e.g. '2026-07-15 02:00 PM').
        purpose: Reason for the visit.
    """
    data = load_data()
    apps_dict = data.setdefault("appointments", {})
    patient_apps = apps_dict.setdefault(patient_name, [])
    
    patient_apps.append({
        "doctor": doctor,
        "datetime_str": datetime_str,
        "purpose": purpose
    })
    save_data(data)
    return f"Successfully scheduled appointment with {doctor} on {datetime_str} for {patient_name}."

@mcp.tool()
def log_health_checkin(patient_name: str, vital_stats: str, notes: str) -> str:
    """Log vital stats and daily notes for a patient.
    
    Args:
        patient_name: The name of the patient.
        vital_stats: Vital signs (e.g. BP 120/80, pulse 70).
        notes: General daily notes on mood, symptoms, or behavior.
    """
    data = load_data()
    checkins_dict = data.setdefault("checkins", {})
    patient_checkins = checkins_dict.setdefault(patient_name, [])
    
    timestamp = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    patient_checkins.append({
        "timestamp": timestamp,
        "vital_stats": vital_stats,
        "notes": notes
    })
    save_data(data)
    return f"Logged health check-in for {patient_name} at {timestamp}."

if __name__ == "__main__":
    mcp.run(transport="stdio")

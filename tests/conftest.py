import sys
from unittest.mock import MagicMock
import google.auth
from google.auth.credentials import AnonymousCredentials

# Mock google.auth.default to return AnonymousCredentials and a dummy project ID
# this avoids DefaultCredentialsError during test collection and execution
google.auth.default = MagicMock(return_value=(AnonymousCredentials(), "dummy-project"))

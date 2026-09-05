"""
Shared In-Memory State across PyMentor modules.
Includes rate limiting buckets, login lockout tables, submit cooldowns, and request tracking.
"""

from collections import deque

# Rate limiting dictionaries
# (roll_no, section) -> (failed_attempts: int, locked_until: float)
login_attempts = {}

# client_ip -> (failed_attempts: int, locked_until: float)
admin_attempts = {}

# student_id -> last_submit_timestamp: float
submit_cooldowns = {}

# Rolling timestamps of recent HTTP requests for RPM metrics
request_times = deque(maxlen=5000)

import sqlite3
import json
import os
from datetime import datetime

import sys
import logging

try:
    import bcrypt
except ImportError:
    logging.critical("CRITICAL: bcrypt library is not installed. Application refusing to start to prevent plaintext password fallback.")
    sys.exit(1)

def hash_password(password: str) -> str:
    # bcrypt requires bytes
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False


DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pymentor.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)  # wait up to 10s for locks (multi-user)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # WAL: concurrent reads + single writer, no blocking
    conn.execute("PRAGMA synchronous=NORMAL") # safe & faster than FULL for WAL mode
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def log_event(student_id=None, session_id=None, problem_id=None, event_type: str = "", event_data=None):
    """Logs an action to the events table for detailed analytics and audit trails."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        data_str = json.dumps(event_data or {})
        cursor.execute("""
        INSERT INTO events (student_id, session_id, problem_id, event_type, event_data, created_at)
        VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))
        """, (student_id, session_id, problem_id, event_type, data_str))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.getLogger("pymentor.database").error(f"Error logging telemetry event: {e}")

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS problems (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL,
        title TEXT NOT NULL,
        difficulty TEXT NOT NULL,
        description TEXT NOT NULL,
        sample_input TEXT NOT NULL,
        sample_output TEXT NOT NULL,
        concepts TEXT NOT NULL,
        starter_code TEXT DEFAULT '',
        ai_rubric TEXT NOT NULL,
        reference_solution TEXT DEFAULT ''
    );
    """)

    # Ensure reference_solution exists in existing databases (Component 4 migration)
    try:
        cursor.execute("ALTER TABLE problems ADD COLUMN reference_solution TEXT DEFAULT ''")
    except Exception:
        pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_no TEXT NOT NULL,
        name TEXT NOT NULL,
        section TEXT NOT NULL,
        password TEXT NOT NULL DEFAULT '123',
        needs_password_change INTEGER DEFAULT 1,
        default_help_level INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
        UNIQUE(roll_no, section)
    );
    """)

    try:
        cursor.execute("ALTER TABLE students ADD COLUMN needs_password_change INTEGER DEFAULT 1")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE students ADD COLUMN default_help_level INTEGER DEFAULT 1")
    except Exception:
        pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        problem_id INTEGER NOT NULL,
        help_level INTEGER DEFAULT 1,
        status TEXT DEFAULT 'in_progress',
        last_code TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
        updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (student_id) REFERENCES students(id),
        FOREIGN KEY (problem_id) REFERENCES problems(id)
    );
    """)

    # Ensure last_code exists in existing databases
    try:
        cursor.execute("ALTER TABLE sessions ADD COLUMN last_code TEXT DEFAULT ''")
    except Exception:
        pass

    # Ensure run_count and time_spent_seconds exist in existing sessions table
    try:
        cursor.execute("ALTER TABLE sessions ADD COLUMN run_count INTEGER DEFAULT 0")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE sessions ADD COLUMN time_spent_seconds INTEGER DEFAULT 0")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE sessions ADD COLUMN last_heartbeat_at TIMESTAMP")
    except Exception:
        pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        code TEXT NOT NULL,
        ai_response TEXT NOT NULL,
        is_correct INTEGER DEFAULT 0,
        attempt_number INTEGER DEFAULT 1,
        model_used TEXT DEFAULT '',
        simulated_output TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    );
    """)

    # Ensure simulated_output exists in existing submissions table
    try:
        cursor.execute("ALTER TABLE submissions ADD COLUMN simulated_output TEXT DEFAULT ''")
    except Exception:
        pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        session_id INTEGER,
        problem_id INTEGER,
        event_type TEXT NOT NULL,
        event_data TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (student_id) REFERENCES students(id),
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (problem_id) REFERENCES problems(id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auth_tokens (
        token TEXT PRIMARY KEY,
        student_id INTEGER NOT NULL,
        expires_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (student_id) REFERENCES students(id)
    );
    """)

    # Ensure expires_at exists in existing databases
    try:
        cursor.execute("ALTER TABLE auth_tokens ADD COLUMN expires_at TIMESTAMP")
    except Exception:
        pass

    # Seed / sync problems
    seed_problems(cursor)

    # Seed authorized students if empty
    cursor.execute("SELECT COUNT(*) as count FROM students")
    s_count = cursor.fetchone()["count"]
    if s_count == 0:
        seed_students(cursor)

    # Migrate plain-text passwords to bcrypt hashes
    cursor.execute("SELECT id, password FROM students")
    for row in cursor.fetchall():
        pid, pwd = row["id"], row["password"]
        # bcrypt hashes start with $2b$ or $2a$, so we can detect plain text
        if pwd and not pwd.startswith("$2"):
            hashed = hash_password(pwd)
            cursor.execute("UPDATE students SET password = ? WHERE id = ?", (hashed, pid))

    conn.commit()
    conn.close()

def seed_students(cursor):
    authorized = []
    for sec in ["E", "F", "G"]:
        for r in range(1, 5):
            authorized.append({
                "roll_no": str(r),
                "name": f"User {r}",
                "section": sec,
                "password": hash_password("123")
            })
    for s in authorized:
        cursor.execute("""
        INSERT OR IGNORE INTO students (roll_no, name, section, password, needs_password_change)
        VALUES (?, ?, ?, ?, 1)
        """, (s["roll_no"], s["name"], s["section"], s["password"]))

def seed_problems(cursor):
    problems = [
        {
                "topic": "Variables & Data Types",
                "title": "Personal Bio-Card Generator",
                "difficulty": "Easy",
                "description": "Write a Python program that asks the user for their name, age, course name, and high-school marks percentage. Print a formatted student bio card displaying these details.",
                "sample_input": "Name: Rohan Sharma\nAge: 18\nCourse: BCA\nPercentage: 85.5",
                "sample_output": "==============================\n      STUDENT BIO CARD        \n==============================\nName       : Rohan Sharma\nAge        : 18 years\nCourse     : BCA\nPercentage : 85.50%\n==============================",
                "concepts": "[\"input()\", \"int()\", \"float()\", \"f-strings\", \"print()\"]",
                "starter_code": "# Ask the user for their details\n# Remember: input() returns text, convert numbers appropriately!\n\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Uses input() for name and course (strings).\n- Uses int(input(...)) for age.\n- Uses float(input(...)) for percentage.\n- Uses f-strings or clean formatting to print the card.\n- Output formatting with :.2f for percentage is a great bonus.\n\nCOMMON BEGINNER MISTAKES:\n- Forgetting to convert age to int or percentage to float (though pure string printing may work, emphasize type conversion).\n- Using commas in input without understanding strings.\n- Typos in variable names.\n- Messy print statements or missing newlines.\n"
        },
        {
                "topic": "Variables & Data Types",
                "title": "College Fee Receipt Calculator",
                "difficulty": "Easy",
                "description": "A college charges Tuition Fee, Bus/Transport Fee, and Lab Examination Fee. Ask the user to input each amount. Calculate the total fee and also compute a 5% early-bird discount on the total amount. Print the subtotal, discount, and net payable fee.",
                "sample_input": "Enter Tuition Fee: 45000\nEnter Transport Fee: 12000\nEnter Lab Exam Fee: 3000",
                "sample_output": "--- FEE RECEIPT ---\nSubtotal   : Rs 60000.00\nDiscount (5%): Rs 3000.00\nNet Payable: Rs 57000.00",
                "concepts": "[\"float conversion\", \"basic arithmetic (+, *, -)\", \"f-string formatting :.2f\"]",
                "starter_code": "# Take tuition, transport, and lab fee as input\n# Calculate total, 5% discount, and net fee\n\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Converts inputs to float() or int().\n- total = tuition + transport + lab.\n- discount = total * 0.05 or total * (5 / 100).\n- net = total - discount.\n- Displays using :.2f formatting.\n\nCOMMON BEGINNER MISTAKES:\n- Adding strings without converting to numbers ('45000' + '12000' = '4500012000').\n- Miscalculating 5% (e.g. dividing by 5 instead of multiplying by 0.05).\n- Forgetting to subtract discount from total.\n"
        },
        {
                "topic": "Variables & Data Types",
                "title": "Temperature Converter (Celsius to Fahrenheit & Kelvin)",
                "difficulty": "Easy",
                "description": "Write a program that takes temperature in Celsius from the user and converts it into Fahrenheit (F = C * 9/5 + 32) and Kelvin (K = C + 273.15). Display both converted values rounded to 2 decimal places.",
                "sample_input": "Enter temperature in Celsius: 37",
                "sample_output": "37.00\u00b0C is equal to:\nFahrenheit : 98.60\u00b0F\nKelvin     : 310.15 K",
                "concepts": "[\"float()\", \"order of operations\", \"formula calculation\", \"round() or :.2f\"]",
                "starter_code": "celsius = float(input(\"Enter temperature in Celsius: \"))\n# Apply formulas and print\n",
                "ai_rubric": "\nVALID APPROACHES:\n- fahrenheit = (celsius * 9/5) + 32 or celsius * 1.8 + 32.\n- kelvin = celsius + 273.15.\n- Both round() and f-string :.2f formatting are acceptable.\n\nCOMMON BEGINNER MISTAKES:\n- Incorrect operator precedence, e.g. celsius * 9 / (5 + 32).\n- Hardcoding values instead of using the user input.\n- Missing float conversion on input().\n"
        },
        {
                "topic": "Operators & Expressions",
                "title": "Time Breakdown (Seconds to Hours, Mins & Secs)",
                "difficulty": "Medium",
                "description": "Given a total number of seconds as an integer input, convert and display it in Hours, Minutes, and remaining Seconds using integer division (//) and modulus (%) operators.",
                "sample_input": "Enter total seconds: 3665",
                "sample_output": "3665 seconds = 1 Hours, 1 Minutes, and 5 Seconds",
                "concepts": "[\"// operator\", \"% operator\", \"int arithmetic\"]",
                "starter_code": "total_seconds = int(input(\"Enter total seconds: \"))\n# Calculate hours, minutes, and remaining seconds using // and %\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Approach 1:\n  hours = total_seconds // 3600\n  rem = total_seconds % 3600\n  minutes = rem // 60\n  seconds = rem % 60\n- Approach 2:\n  minutes_total = total_seconds // 60\n  seconds = total_seconds % 60\n  hours = minutes_total // 60\n  minutes = minutes_total % 60\n\nCOMMON BEGINNER MISTAKES:\n- Using / (float division) instead of // (floor division), resulting in fractional seconds.\n- Forgetting that an hour has 3600 seconds, not 60.\n- Reusing variable names incorrectly.\n"
        },
        {
                "topic": "Operators & Expressions",
                "title": "Restaurant Bill & Tip Splitter",
                "difficulty": "Easy",
                "description": "Ask for the food bill amount, tip percentage (e.g. 10 for 10%), and the number of friends sharing the bill. Calculate total tip, total bill with tip, and amount each person must pay. Format each to 2 decimal places.",
                "sample_input": "Enter food bill: 1500\nEnter tip percentage: 10\nEnter number of people: 3",
                "sample_output": "Tip Amount : Rs 150.00\nTotal Bill : Rs 1650.00\nPer Person : Rs 550.00",
                "concepts": "[\"arithmetic operators\", \"division\", \"f-strings :.2f\"]",
                "starter_code": "# Take input for bill, tip percentage, and number of people\n\n",
                "ai_rubric": "\nVALID APPROACHES:\n- tip_amount = bill * (tip_percent / 100)\n- total_bill = bill + tip_amount\n- per_person = total_bill / people\n\nCOMMON BEGINNER MISTAKES:\n- tip = bill * tip_percent (forgetting / 100).\n- Dividing bill by people before adding tip and getting wrong rounding.\n- Dividing by zero not handled (acceptable at beginner stage, but praiseworthy if mentioned).\n"
        },
        {
                "topic": "Python Math Module",
                "title": "Room Painting & Flooring Estimator",
                "difficulty": "Medium",
                "description": "A contractor needs to paint the 4 walls of a rectangular room and measure the floor diagonal for tile alignment.\nInputs: room length, width, and height (in meters).\nFormulas:\n1. Total wall area = 2 * height * (length + width)\n2. One can of paint covers 10 sq.m. You CANNOT buy partial cans, so round UP using math.ceil().\n3. Floor diagonal = sqrt(length^2 + width^2) using math.sqrt() and math.pow().\nDisplay wall area (2 decimal places), cans needed (integer), and floor diagonal (2 decimal places).",
                "sample_input": "Enter length (m): 6.5\nEnter width (m): 4.0\nEnter height (m): 3.0",
                "sample_output": "Wall Area     : 63.00 sq m\nCans Required : 7 cans\nFloor Diagonal: 7.63 m",
                "concepts": "[\"import math\", \"math.ceil()\", \"math.sqrt()\", \"math.pow()\", \":.2f formatting\"]",
                "starter_code": "import math\n\nlength = float(input(\"Enter length (m): \"))\nwidth = float(input(\"Enter width (m): \"))\nheight = float(input(\"Enter height (m): \"))\n\n# Perform calculations using math.ceil and math.sqrt\n",
                "ai_rubric": "\nVALID APPROACHES:\n- import math at the top.\n- wall_area = 2 * height * (length + width)\n- cans = math.ceil(wall_area / 10)\n- diagonal = math.sqrt(math.pow(length, 2) + math.pow(width, 2)) or math.sqrt(length**2 + width**2) or math.hypot(length, width).\n\nCOMMON BEGINNER MISTAKES:\n- Using round() or int() instead of math.ceil() for cans (if wall_area is 63, 63/10 is 6.3; int() gives 6, but 6 cans leave 3 sq.m unpainted!).\n- Forgetting to import math.\n- Incorrect wall area formula (e.g. including floor or ceiling).\n"
        },
        {
                "topic": "Python Math Module",
                "title": "Cylinder Surface Area & Volume Calculator",
                "difficulty": "Medium",
                "description": "Write a program that takes the radius and height of a cylinder from the user and calculates:\n1. Curved Surface Area = 2 * pi * r * h\n2. Total Surface Area = 2 * pi * r * (r + h)\n3. Volume = pi * r^2 * h\nUse math.pi and math.pow() from the math module. Print all results rounded to 2 decimal places.",
                "sample_input": "Enter radius: 5\nEnter height: 12",
                "sample_output": "Curved Surface Area: 376.99\nTotal Surface Area : 534.07\nVolume             : 942.48",
                "concepts": "[\"import math\", \"math.pi\", \"math.pow()\", \"f-string :.2f\"]",
                "starter_code": "import math\n\nr = float(input(\"Enter radius: \"))\nh = float(input(\"Enter height: \"))\n\n# Calculate using math.pi and math.pow()\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Uses math.pi instead of hardcoded 3.14.\n- Uses math.pow(r, 2) or r ** 2.\n- Formats outputs cleanly with :.2f.\n\nCOMMON BEGINNER MISTAKES:\n- Using 3.14 or 22/7 instead of math.pi.\n- Forgetting parentheses in total surface area: 2 * pi * r * (r + h).\n- Confusing curved surface area with total surface area.\n"
        },
        {
                "topic": "Decision Making (if / else)",
                "title": "Voting Eligibility & Remaining Years",
                "difficulty": "Easy",
                "description": "Write a program to ask for the user's age. If the age is 18 or above, print 'Eligible to Vote!'. Otherwise, print 'Not eligible yet.' and calculate and display how many years they must wait until they become eligible.",
                "sample_input": "Enter your age: 15",
                "sample_output": "Not eligible yet.\nYou must wait 3 more year(s) to vote.",
                "concepts": "[\"if-else\", \"relational operator >=\", \"subtraction in else block\"]",
                "starter_code": "age = int(input(\"Enter your age: \"))\n\n# Check eligibility using if-else\n",
                "ai_rubric": "\nVALID APPROACHES:\n- if age >= 18: print eligible.\n- else: years_left = 18 - age; print wait years_left.\n- Can also check if age < 18 first, both are completely valid logic structures.\n\nCOMMON BEGINNER MISTAKES:\n- Using = instead of == or >=.\n- Forgetting colon (:) after if or else.\n- Indentation errors in the else block.\n- Calculating 18 - age in the if branch instead of the else branch.\n"
        },
        {
                "topic": "Decision Making (if / else)",
                "title": "Student Grade Classifier",
                "difficulty": "Medium",
                "description": "Ask the user to enter their exam marks (0 to 100).\n1. First check if marks are valid (between 0 and 100). If not, print 'Invalid Marks! Must be between 0 and 100.'\n2. If valid, assign grades:\n   - 90 to 100: Grade A+\n   - 80 to 89: Grade A\n   - 70 to 79: Grade B\n   - 60 to 69: Grade C\n   - 40 to 59: Grade D (Pass)\n   - Below 40: Grade F (Fail)",
                "sample_input": "Enter marks: 84",
                "sample_output": "Result: Grade A",
                "concepts": "[\"if-elif-else\", \"chained comparison\", \"logical and\", \"input validation\"]",
                "starter_code": "marks = float(input(\"Enter marks (0-100): \"))\n\n# Validate input and assign grade\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Validate using if marks < 0 or marks > 100: ...\n- Then elif marks >= 90: Grade A+\n- elif marks >= 80: Grade A (no need for <= 89 because top-down evaluation handles it!)\n- Praise student if they realize >= 80 is enough without repeating <= 89.\n- Both chained comparisons (80 <= marks <= 89) and pure elif hierarchies are valid.\n\nCOMMON BEGINNER MISTAKES:\n- Using multiple independent 'if' statements instead of 'elif', causing multiple grades to print!\n- Ordering conditions backwards (e.g. checking marks >= 40 first, which triggers for 95 too!).\n- Missing validation for negative numbers or marks > 100.\n"
        },
        {
                "topic": "Decision Making (if / else)",
                "title": "Positive, Negative, or Zero with Parity",
                "difficulty": "Easy",
                "description": "Write a program that takes an integer from the user. First, determine whether the number is Positive, Negative, or Zero. If the number is non-zero, also tell whether it is Even or Odd.",
                "sample_input": "Enter an integer: -14",
                "sample_output": "The number is Negative and Even.",
                "concepts": "[\"if-elif-else\", \"modulus %\", \"nested if or combined if\"]",
                "starter_code": "num = int(input(\"Enter an integer: \"))\n\n# Check sign and parity\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Check num == 0 first, or check sign first then parity.\n- Can use nested conditions or separate variables:\n  sign = 'Positive' if num > 0 else 'Negative'\n  parity = 'Even' if num % 2 == 0 else 'Odd'\n- Multiple approaches are all valid.\n\nCOMMON BEGINNER MISTAKES:\n- Saying 0 is Positive or Negative.\n- Trying to compute parity on 0 (while 0 is mathematically even, saying 'Zero and Even' is clunky unless specified).\n- Confusion with negative modulus (in Python -14 % 2 is 0, which works!).\n"
        },
        {
                "topic": "Nested Conditions",
                "title": "ATM Cash Withdrawal Simulator",
                "difficulty": "Hard",
                "description": "Simulate an ATM cash withdrawal:\n- Initial account balance is fixed at Rs 25,000.\n- Correct secret PIN is 4321.\nSteps:\n1. Ask the user for their 4-digit PIN.\n2. If PIN is incorrect, print 'Access Denied: Incorrect PIN!'.\n3. If PIN is correct, ask for withdrawal amount.\n4. Check if amount > 0. If not, print 'Error: Withdrawal amount must be positive!'.\n5. Check if amount is a multiple of 100 (ATM dispenses 100/500 notes). If not, print 'Error: Amount must be in multiples of 100!'.\n6. Check if amount <= balance. If yes, deduct and print new balance. If no, print 'Error: Insufficient funds!'.",
                "sample_input": "Enter PIN: 4321\nEnter withdrawal amount: 3500",
                "sample_output": "Transaction Successful!\nWithdrawn  : Rs 3500\nNew Balance: Rs 21500",
                "concepts": "[\"nested if\", \"modulus % 100\", \"multiple validations\", \"state update\"]",
                "starter_code": "balance = 25000\nCORRECT_PIN = 4321\n\n# Write nested checks for PIN, positivity, multiples of 100, and balance\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Nested structure:\n  if pin == CORRECT_PIN:\n      amount = int(input(...))\n      if amount <= 0: ...\n      elif amount % 100 != 0: ...\n      elif amount > balance: ...\n      else: balance -= amount ...\n- Early exit or sequential validation structures are all valid.\n\nCOMMON BEGINNER MISTAKES:\n- Deducting money even when insufficient funds or wrong PIN.\n- Checking amount before verifying PIN.\n- Forgetting amount % 100 == 0 check.\n- Using = instead of == for PIN verification.\n"
        },
        {
                "topic": "Nested Conditions",
                "title": "Gregorian Leap Year Precision Checker",
                "difficulty": "Medium",
                "description": "Write a program to determine if a given year is a Leap Year according to standard calendar rules:\n1. A year is a leap year if it is divisible by 4 AND not divisible by 100.\n2. EXCEPT years divisible by 400 ARE leap years (e.g. 2000 was a leap year, but 1900 was not).\nAsk the user for a year and print whether it is a Leap Year with a brief explanation.",
                "sample_input": "Enter a year: 2024",
                "sample_output": "2024 is a LEAP YEAR! (Divisible by 4 and not a century year)",
                "concepts": "[\"logical and / or\", \"modulus %\", \"nested conditions\"]",
                "starter_code": "year = int(input(\"Enter a year: \"))\n\n# Check leap year rules\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Approach 1 (Single combined condition):\n  if (year % 400 == 0) or (year % 4 == 0 and year % 100 != 0):\n      ...\n- Approach 2 (Nested / elif hierarchy):\n  if year % 400 == 0: ...\n  elif year % 100 == 0: ...\n  elif year % 4 == 0: ...\n  else: ...\n\nCOMMON BEGINNER MISTAKES:\n- Only checking year % 4 == 0 (fails for 1900, 2100).\n- Incorrect order of checks in elif (checking % 4 before % 100).\n- Wrong parentheses in the combined boolean condition.\n"
        },
        {
                "topic": "Nested Conditions",
                "title": "Tiered Electricity Consumption Bill",
                "difficulty": "Hard",
                "description": "Calculate an electricity bill based on units consumed using slab-based pricing:\n- Units <= 100: Rs 4.50 per unit\n- Units 101 to 200: First 100 @ Rs 4.50, remaining @ Rs 6.00 per unit\n- Units 201 to 300: First 100 @ Rs 4.50, next 100 @ Rs 6.00, remaining @ Rs 8.00 per unit\n- Units above 300: First 100 @ Rs 4.50, next 100 @ Rs 6.00, next 100 @ Rs 8.00, remaining @ Rs 10.50 per unit\nA fixed meter surcharge of Rs 50 is added to all bills. Print total units, energy charge, surcharge, and total bill rounded to 2 decimal places.",
                "sample_input": "Enter units consumed: 250",
                "sample_output": "--- ELECTRICITY BILL ---\nUnits Consumed : 250\nEnergy Charges : Rs 1450.00\nMeter Surcharge: Rs 50.00\nTotal Payable  : Rs 1500.00",
                "concepts": "[\"cumulative slab calculation\", \"if-elif-else\", \"float calculations\", \":.2f\"]",
                "starter_code": "units = float(input(\"Enter units consumed: \"))\nSURCHARGE = 50.0\n\n# Calculate slab-wise bill\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Cumulative slab calculation:\n  For units = 250:\n  100 * 4.50 + 100 * 6.00 + (250 - 200) * 8.00 = 450 + 600 + 400 = 1450.\n- Surcharge of 50 added at the end.\n\nCOMMON BEGINNER MISTAKES:\n- Flat-rate multiplication instead of slab: e.g. calculating 250 * 8.00 = 2000 (wrong!).\n- Forgetting to subtract previous slab boundaries: (units - 100), (units - 200), etc.\n- Forgetting the Rs 50 surcharge.\n"
        },
        {
                "topic": "Variables & Data Types",
                "title": "Simple Interest & Maturity Value Calculator",
                "difficulty": "Easy",
                "description": "Write a program for a bank teller that takes the Principal amount (in Rs), Annual Interest Rate (in percentage), and Time duration (in years) as input.\nCalculate the Simple Interest using the formula:\nSI = (P * R * T) / 100\nand the Total Maturity Amount = Principal + SI.\nDisplay both values formatted to 2 decimal places.",
                "sample_input": "Enter Principal Amount (Rs): 50000\nEnter Annual Rate of Interest (%): 7.5\nEnter Time Period (years): 3",
                "sample_output": "------------------------------\n        FIXED DEPOSIT         \n------------------------------\nPrincipal Amount : Rs 50000.00\nInterest Rate    : 7.50%\nTime Period      : 3.0 years\nSimple Interest  : Rs 11250.00\nTotal Maturity   : Rs 61250.00\n------------------------------",
                "concepts": "[\"float()\", \"arithmetic formulas\", \"f-strings :.2f\"]",
                "starter_code": "# Take Principal, Rate, and Time from user\n# Remember to convert inputs to float!\n\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Converts inputs using float().\n- Calculates SI = (p * r * t) / 100.\n- Calculates total = p + SI.\n- Formats outputs cleanly with :.2f.\n\nCOMMON BEGINNER MISTAKES:\n- Missing float conversion on input().\n- Misplacing parentheses in (p * r * t) / 100.\n- Forgetting to add SI to Principal to get Total Maturity.\n"
        },
        {
                "topic": "Variables & Data Types",
                "title": "Student Semester GPA & Marks Sheet",
                "difficulty": "Easy",
                "description": "Create a marks sheet calculator for a BCA student. Ask for Student Name, Roll Number, and marks obtained out of 100 in 3 subjects: Python Programming, Mathematics, and Computer Fundamentals.\nCalculate the Total Marks (out of 300) and the Overall Percentage.\nPrint a neat, formatted report card displaying all details.",
                "sample_input": "Enter Student Name: Priya Verma\nEnter Roll Number: 104\nEnter Python Marks: 88.5\nEnter Math Marks: 92.0\nEnter Computer Fundamentals Marks: 79.5",
                "sample_output": "========================================\n         BCA SEMESTER MARKS SHEET       \n========================================\nStudent Name : Priya Verma\nRoll Number  : 104\nTotal Marks  : 260.00 / 300\nPercentage   : 86.67%\n========================================",
                "concepts": "[\"input()\", \"float()\", \"string formatting\", \"arithmetic (+) and (/)\"]",
                "starter_code": "# Input student details and marks for 3 subjects\n# Compute total and percentage, then format report card\n\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Reads name and roll as strings.\n- Converts subject marks to float().\n- total = m1 + m2 + m3.\n- percentage = (total / 300) * 100.\n- Formats percentage with :.2f.\n\nCOMMON BEGINNER MISTAKES:\n- Adding strings without converting marks to float.\n- Dividing by 300 without multiplying by 100.\n- Typos in variable names.\n"
        },
        {
                "topic": "Operators & Expressions",
                "title": "Cash Dispenser Denomination Breakdown",
                "difficulty": "Medium",
                "description": "An automated bank cash dispenser dispenses notes in denominations of Rs 500, Rs 200, Rs 100, and Rs 50.\nAsk the user for a total withdrawal amount (assumed to be a multiple of 50).\nUse integer floor division (//) and modulus (%) to calculate and display the minimum number of each note dispensed.",
                "sample_input": "Enter withdrawal amount (Rs): 3850",
                "sample_output": "Notes dispensed for Rs 3850:\nRs 500 notes : 7\nRs 200 notes : 1\nRs 100 notes : 1\nRs 50 notes  : 1",
                "concepts": "[\"// floor division\", \"% modulus\", \"sequential remainder calculation\"]",
                "starter_code": "amount = int(input(\"Enter withdrawal amount (Rs): \"))\n\n# Use // to find count of 500s, % to find remainder, then repeat for 200, 100, 50\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Sequential floor division and modulus:\n  n500 = amount // 500\n  rem = amount % 500\n  n200 = rem // 200\n  rem = rem % 200\n  n100 = rem // 100\n  rem = rem % 100\n  n50 = rem // 50\n- Alternatively, subtracting the dispensed value: rem -= n500 * 500.\n\nCOMMON BEGINNER MISTAKES:\n- Using float division / instead of // resulting in floats.\n- Using original amount repeatedly instead of remainder (e.g. amount // 200).\n- Forgetting to print all denomination counts.\n"
        },
        {
                "topic": "Operators & Expressions",
                "title": "2D Coordinate Distance (Euclidean Distance)",
                "difficulty": "Medium",
                "description": "Write a program to calculate the straight-line distance between two points in a 2D Cartesian plane: Point 1 (x1, y1) and Point 2 (x2, y2).\nUse the Euclidean formula:\ndistance = sqrt((x2 - x1)^2 + (y2 - y1)^2) using exponentiation (**).\nDisplay the coordinates and the resulting distance rounded to 2 decimal places.",
                "sample_input": "Enter x1: 2\nEnter y1: 3\nEnter x2: 6\nEnter y2: 6",
                "sample_output": "Point 1 : (2.00, 3.00)\nPoint 2 : (6.00, 6.00)\nDistance: 5.00 units",
                "concepts": "[\"float()\", \"** exponentiation operator\", \"order of operations ()\", \":.2f formatting\"]",
                "starter_code": "# Read x1, y1, x2, y2\n# Calculate Euclidean distance using ** 0.5\n\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Converts inputs to float.\n- dx = x2 - x1\n- dy = y2 - y1\n- distance = (dx**2 + dy**2) ** 0.5 (or math.sqrt).\n- Formats to 2 decimal places.\n\nCOMMON BEGINNER MISTAKES:\n- Missing parentheses around (dx**2 + dy**2) ** 0.5 causing order of operations bug.\n- Using ^ instead of ** for power in Python.\n- Missing float conversion on coordinates.\n"
        },
        {
                "topic": "Operators & Expressions",
                "title": "Variable Value Inversion & Swapping",
                "difficulty": "Easy",
                "description": "Ask the user to enter two integers: a and b.\nDisplay their values before swapping.\nThen, swap the two variables so that 'a' gets the value of 'b' and 'b' gets the value of 'a'.\nDisplay the swapped values.\nTry using Python's simultaneous assignment (a, b = b, a) or a temporary variable!",
                "sample_input": "Enter first number (a): 15\nEnter second number (b): 40",
                "sample_output": "Before Swap: a = 15, b = 40\nAfter Swap : a = 40, b = 15",
                "concepts": "[\"variable assignment\", \"tuple unpacking a, b = b, a\", \"value mutation\"]",
                "starter_code": "a = int(input(\"Enter first number (a): \"))\nb = int(input(\"Enter second number (b): \"))\n\n# Print before swap, perform swap, then print after swap\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Pythonic tuple swap: a, b = b, a\n- Temp variable: temp = a; a = b; b = temp\n- Arithmetic swap: a = a + b; b = a - b; a = a - b\n\nCOMMON BEGINNER MISTAKES:\n- Doing a = b; b = a without temp, which overwrites a and makes both numbers equal to b!\n- Printing fake swapped values without actually swapping the variables.\n"
        },
        {
                "topic": "Python Math Module",
                "title": "Compound Interest & Wealth Growth Calculator",
                "difficulty": "Medium",
                "description": "Write a program to compute annually compounded interest using the formula:\nA = P * (1 + r / 100)^t\nwhere P is principal, r is annual interest rate (%), and t is time in years.\nUse math.pow() from the math module.\nCalculate Compound Interest = A - P.\nPrint Principal, Compound Interest, and Total Maturity rounded to 2 decimal places.",
                "sample_input": "Enter Principal (Rs): 100000\nEnter Annual Rate (%): 8.5\nEnter Time in Years: 5",
                "sample_output": "--- COMPOUND INTEREST BREAKDOWN ---\nPrincipal Invested : Rs 100000.00\nCompound Interest  : Rs 50365.67\nTotal Maturity     : Rs 150365.67\n-----------------------------------",
                "concepts": "[\"import math\", \"math.pow()\", \"exponential formula\", \"f-string :.2f\"]",
                "starter_code": "import math\n\np = float(input(\"Enter Principal (Rs): \"))\nr = float(input(\"Enter Annual Rate (%): \"))\nt = float(input(\"Enter Time in Years: \"))\n\n# Calculate maturity using math.pow() and compound interest\n",
                "ai_rubric": "\nVALID APPROACHES:\n- import math\n- amount = p * math.pow(1 + (r / 100), t)\n- ci = amount - p\n- Clean :.2f formatting.\n\nCOMMON BEGINNER MISTAKES:\n- Forgetting to import math.\n- Forgetting to divide rate by 100.\n- Confusing compound interest (A - P) with the final amount (A).\n"
        },
        {
                "topic": "Python Math Module",
                "title": "Right-Angled Triangle Trigonometry & Incline Angle",
                "difficulty": "Medium",
                "description": "A civil engineering ramp has a horizontal Base and vertical Perpendicular Height (in meters).\nUsing Python's math module:\n1. Compute the Hypotenuse ramp length using math.hypot() or math.sqrt().\n2. Compute the ramp angle of inclination in radians using math.atan(height / base) and convert it to degrees using math.degrees().\nDisplay ramp length and angle in degrees rounded to 2 decimal places.",
                "sample_input": "Enter horizontal base (m): 12.0\nEnter vertical height (m): 5.0",
                "sample_output": "Ramp Length (Hypotenuse): 13.00 m\nAngle of Inclination    : 22.62 degrees",
                "concepts": "[\"import math\", \"math.hypot()\", \"math.atan()\", \"math.degrees()\", \":.2f\"]",
                "starter_code": "import math\n\nbase = float(input(\"Enter horizontal base (m): \"))\nheight = float(input(\"Enter vertical height (m): \"))\n\n# Calculate hypotenuse and incline angle in degrees\n",
                "ai_rubric": "\nVALID APPROACHES:\n- import math\n- hypotenuse = math.hypot(base, height) or math.sqrt(base**2 + height**2)\n- angle_deg = math.degrees(math.atan(height / base))\n- Formats to 2 decimal places.\n\nCOMMON BEGINNER MISTAKES:\n- Forgetting to convert radians to degrees (printing atan directly gives ~0.39 instead of 22.62 degrees).\n- Inverting base and height in atan: math.atan(base / height).\n"
        },
        {
                "topic": "Python Math Module",
                "title": "Sphere Volume & Surface Area Calculator",
                "difficulty": "Easy",
                "description": "Write a program that takes the radius of a spherical water tank (in meters) and calculates:\n1. Surface Area = 4 * pi * r^2\n2. Volume = (4/3) * pi * r^3\nUse math.pi and math.pow() from the math module. Print both results rounded to 2 decimal places.",
                "sample_input": "Enter radius of sphere (m): 3.5",
                "sample_output": "Radius       : 3.50 m\nSurface Area : 153.94 sq m\nVolume       : 179.59 cubic m",
                "concepts": "[\"import math\", \"math.pi\", \"math.pow()\", \"formula execution\", \":.2f\"]",
                "starter_code": "import math\n\nr = float(input(\"Enter radius of sphere (m): \"))\n\n# Compute Surface Area and Volume using math.pi and math.pow()\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Uses math.pi and math.pow().\n- area = 4 * math.pi * math.pow(r, 2)\n- volume = (4 / 3) * math.pi * math.pow(r, 3)\n- Formats to 2 decimal places.\n\nCOMMON BEGINNER MISTAKES:\n- Using 3.14 instead of math.pi.\n- Incorrect volume formula (e.g. using r^2 for volume or omitting 4/3).\n"
        },
        {
                "topic": "Decision Making (if / else)",
                "title": "Theme Park Rollercoaster Entry & FastPass Gate (Lab 04)",
                "difficulty": "Easy",
                "description": "A theme park rollercoaster requires riders to meet safety regulations:\n- Minimum age: 12 years\n- Minimum height: 140 cm\nAsk the user for rider's Age and Height.\n1. If both Age >= 12 AND Height >= 140: Print 'Access Granted: Enjoy the thrill ride!'.\n2. Otherwise, print 'Access Denied: You do not meet safety requirements.' and display which specific requirement(s) they failed.",
                "sample_input": "Enter rider age: 11\nEnter rider height (cm): 145",
                "sample_output": "Access Denied: You do not meet safety requirements.\n- Must be at least 12 years old (you are 11).",
                "concepts": "[\"if-elif-else\", \"logical and\", \"comparison operators >=\", \"conditional diagnostics\"]",
                "starter_code": "age = int(input(\"Enter rider age: \"))\nheight = float(input(\"Enter rider height (cm): \"))\n\n# Check age and height conditions\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Checks if age >= 12 and height >= 140: Access Granted.\n- Else: displays Access Denied and details whether age < 12, height < 140, or both.\n\nCOMMON BEGINNER MISTAKES:\n- Using 'or' instead of 'and' for permission check.\n- Omitting specific rejection diagnostic message.\n"
        },
        {
                "topic": "Decision Making (if / else)",
                "title": "Triangle Validity & Geometric Type Classifier",
                "difficulty": "Medium",
                "description": "Write a program that takes three side lengths of a triangle: a, b, and c.\n1. First, check if the sides form a valid triangle using the Triangle Inequality Theorem: the sum of any two sides must be strictly greater than the third side (a + b > c and a + c > b and b + c > a).\nIf not, print 'Invalid Triangle: The given sides cannot form a triangle!'.\n2. If valid, classify the triangle:\n   - Equilateral: All 3 sides are equal\n   - Isosceles: Exactly 2 sides are equal\n   - Scalene: All 3 sides are different\nPrint the validity and type.",
                "sample_input": "Enter side a: 7\nEnter side b: 7\nEnter side c: 10",
                "sample_output": "Valid Triangle: YES\nType: Isosceles Triangle",
                "concepts": "[\"if-elif-else\", \"logical and / or\", \"triangle inequality theorem\", \"nested conditions\"]",
                "starter_code": "a = float(input(\"Enter side a: \"))\nb = float(input(\"Enter side b: \"))\nc = float(input(\"Enter side c: \"))\n\n# Check validity first, then classify type\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Check triangle inequality: a + b > c and a + c > b and b + c > a.\n- If valid:\n  if a == b == c: Equilateral\n  elif a == b or b == c or a == c: Isosceles\n  else: Scalene\n- Else: print Invalid Triangle.\n\nCOMMON BEGINNER MISTAKES:\n- Checking only one sum instead of all three combinations (a + b > c).\n- Checking isosceles before equilateral (which would wrongly classify an equilateral triangle as isosceles).\n"
        },
        {
                "topic": "Nested Conditions",
                "title": "Shopping Mall Discount & Membership Billing (Lab 06)",
                "difficulty": "Medium",
                "description": "A mega-store calculates discounts on shopping bills:\n1. Base purchase discounts:\n   - Bill >= Rs 5,000: 10% discount\n   - Bill >= Rs 2,000 and < 5,000: 5% discount\n   - Bill < Rs 2,000: No base discount\n2. Membership status bonus (applied to subtotal after base discount):\n   - 'Gold': Extra 5% off\n   - 'Silver': Extra 3% off\n   - 'None': No bonus discount\n3. Add 18% GST on the final discounted amount.\nPrint Original Bill, Base Discount, Membership Discount, GST, and Final Payable Amount (all to 2 decimal places).",
                "sample_input": "Enter bill amount (Rs): 6000\nEnter membership status (Gold/Silver/None): Gold",
                "sample_output": "----------------------------------------\n               SUPERMART BILL           \n----------------------------------------\nOriginal Bill       : Rs 6000.00\nBase Discount (10%) : Rs 600.00\nSubtotal            : Rs 5400.00\nGold Discount (5%)  : Rs 270.00\nTaxable Amount      : Rs 5130.00\nGST (18%)           : Rs 923.40\nTotal Payable       : Rs 6053.40\n----------------------------------------",
                "concepts": "[\"nested if-else\", \"string handling\", \"multi-tier percentage math\", \":.2f\"]",
                "starter_code": "bill = float(input(\"Enter bill amount (Rs): \"))\nmembership = input(\"Enter membership status (Gold/Silver/None): \").strip().capitalize()\n\n# Calculate base discount, membership discount, GST, and total\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Base discount based on bill:\n  if bill >= 5000: base_disc = bill * 0.10\n  elif bill >= 2000: base_disc = bill * 0.05\n  else: base_disc = 0\n- subtotal = bill - base_disc\n- Membership discount on subtotal:\n  if membership == 'Gold': mem_disc = subtotal * 0.05\n  elif membership == 'Silver': mem_disc = subtotal * 0.03\n  else: mem_disc = 0\n- taxable = subtotal - mem_disc\n- gst = taxable * 0.18\n- total = taxable + gst\n\nCOMMON BEGINNER MISTAKES:\n- Calculating membership discount on original bill instead of subtotal.\n- Forgetting GST or applying GST before discounts.\n- Case-sensitive string matching bugs (e.g. 'gold' vs 'Gold').\n"
        },
        {
                "topic": "Nested Conditions",
                "title": "Income Tax Slab & Surcharge Calculator",
                "difficulty": "Hard",
                "description": "Calculate annual income tax based on the simplified tax slabs:\n- Income up to Rs 3,00,000: Nil (0%)\n- Rs 3,00,001 to Rs 6,00,000: 5% on amount above Rs 3,00,000\n- Rs 6,00,001 to Rs 9,00,000: Rs 15,000 + 10% on amount above Rs 6,00,000\n- Rs 9,00,001 to Rs 12,00,000: Rs 45,000 + 15% on amount above Rs 9,00,000\n- Above Rs 12,00,000: Rs 90,000 + 20% on amount above Rs 12,00,000\nAdd a mandatory 4% Health and Education Cess on the computed base tax.\nDisplay Gross Income, Base Tax, Cess (4%), and Total Tax Payable.",
                "sample_input": "Enter annual income (Rs): 850000",
                "sample_output": "========================================\n            ANNUAL TAX SUMMARY          \n========================================\nGross Annual Income : Rs 850000.00\nBase Income Tax     : Rs 40000.00\nCess (4%)           : Rs 1600.00\nTotal Tax Payable   : Rs 41600.00\n========================================",
                "concepts": "[\"nested if-elif-else\", \"slab-wise tax math\", \"tax deduction and cess calculation\", \":.2f\"]",
                "starter_code": "income = float(input(\"Enter annual income (Rs): \"))\n\n# Calculate slab-wise base tax, 4% cess, and total tax payable\n",
                "ai_rubric": "\nVALID APPROACHES:\n- Slab calculation:\n  if income <= 300000: tax = 0\n  elif income <= 600000: tax = (income - 300000) * 0.05\n  elif income <= 900000: tax = 15000 + (income - 600000) * 0.10\n  elif income <= 1200000: tax = 45000 + (income - 900000) * 0.15\n  else: tax = 90000 + (income - 1200000) * 0.20\n- cess = tax * 0.04\n- total = tax + cess\n- Formats outputs with :.2f.\n\nCOMMON BEGINNER MISTAKES:\n- Flat rate taxing the entire income at highest percentage.\n- Forgetting the 4% cess.\n"
        }
]

    for p in problems:
        cursor.execute("SELECT id FROM problems WHERE title = ?", (p["title"],))
        if not cursor.fetchone():
            cursor.execute("""
            INSERT INTO problems (topic, title, difficulty, description, sample_input, sample_output, concepts, starter_code, ai_rubric)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p["topic"],
                p["title"],
                p["difficulty"],
                p["description"],
                p["sample_input"],
                p["sample_output"],
                p["concepts"],
                p["starter_code"],
                p["ai_rubric"]
            ))

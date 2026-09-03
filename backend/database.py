"""
Database schema, connection management, and initial problem seeding for PyMentor.
Uses SQLite for lightweight, zero-configuration local storage.
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pymentor.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)  # wait up to 10s for locks (multi-user)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # WAL: concurrent reads + single writer, no blocking
    conn.execute("PRAGMA synchronous=NORMAL") # safe & faster than FULL for WAL mode
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

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
        ai_rubric TEXT NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_no TEXT NOT NULL,
        name TEXT NOT NULL,
        section TEXT NOT NULL,
        password TEXT NOT NULL DEFAULT '123',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(roll_no, section)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        problem_id INTEGER NOT NULL,
        help_level INTEGER DEFAULT 1,
        status TEXT DEFAULT 'in_progress',
        last_code TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES students(id),
        FOREIGN KEY (problem_id) REFERENCES problems(id)
    );
    """)

    # Ensure last_code exists in existing databases
    try:
        cursor.execute("ALTER TABLE sessions ADD COLUMN last_code TEXT DEFAULT ''")
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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    );
    """)

    # Seed problems if empty
    cursor.execute("SELECT COUNT(*) as count FROM problems")
    count = cursor.fetchone()["count"]
    if count == 0:
        seed_problems(cursor)

    # Seed authorized students if empty
    cursor.execute("SELECT COUNT(*) as count FROM students")
    s_count = cursor.fetchone()["count"]
    if s_count == 0:
        seed_students(cursor)

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
                "password": "123"
            })
    for s in authorized:
        cursor.execute("""
        INSERT OR IGNORE INTO students (roll_no, name, section, password)
        VALUES (?, ?, ?, ?)
        """, (s["roll_no"], s["name"], s["section"], s["password"]))

def seed_problems(cursor):
    problems = [
        # Topic 1: Variables, Data Types & Input/Output
        {
            "topic": "Variables & Data Types",
            "title": "Personal Bio-Card Generator",
            "difficulty": "Easy",
            "description": "Write a Python program that asks the user for their name, age, course name, and high-school marks percentage. Print a formatted student bio card displaying these details.",
            "sample_input": "Name: Rohan Sharma\nAge: 18\nCourse: BCA\nPercentage: 85.5",
            "sample_output": "==============================\n      STUDENT BIO CARD        \n==============================\nName       : Rohan Sharma\nAge        : 18 years\nCourse     : BCA\nPercentage : 85.50%\n==============================",
            "concepts": json.dumps(["input()", "int()", "float()", "f-strings", "print()"]),
            "starter_code": "# Ask the user for their details\n# Remember: input() returns text, convert numbers appropriately!\n\n",
            "ai_rubric": """
VALID APPROACHES:
- Uses input() for name and course (strings).
- Uses int(input(...)) for age.
- Uses float(input(...)) for percentage.
- Uses f-strings or clean formatting to print the card.
- Output formatting with :.2f for percentage is a great bonus.

COMMON BEGINNER MISTAKES:
- Forgetting to convert age to int or percentage to float (though pure string printing may work, emphasize type conversion).
- Using commas in input without understanding strings.
- Typos in variable names.
- Messy print statements or missing newlines.
"""
        },
        {
            "topic": "Variables & Data Types",
            "title": "College Fee Receipt Calculator",
            "difficulty": "Easy",
            "description": "A college charges Tuition Fee, Bus/Transport Fee, and Lab Examination Fee. Ask the user to input each amount. Calculate the total fee and also compute a 5% early-bird discount on the total amount. Print the subtotal, discount, and net payable fee.",
            "sample_input": "Enter Tuition Fee: 45000\nEnter Transport Fee: 12000\nEnter Lab Exam Fee: 3000",
            "sample_output": "--- FEE RECEIPT ---\nSubtotal   : Rs 60000.00\nDiscount (5%): Rs 3000.00\nNet Payable: Rs 57000.00",
            "concepts": json.dumps(["float conversion", "basic arithmetic (+, *, -)", "f-string formatting :.2f"]),
            "starter_code": "# Take tuition, transport, and lab fee as input\n# Calculate total, 5% discount, and net fee\n\n",
            "ai_rubric": """
VALID APPROACHES:
- Converts inputs to float() or int().
- total = tuition + transport + lab.
- discount = total * 0.05 or total * (5 / 100).
- net = total - discount.
- Displays using :.2f formatting.

COMMON BEGINNER MISTAKES:
- Adding strings without converting to numbers ('45000' + '12000' = '4500012000').
- Miscalculating 5% (e.g. dividing by 5 instead of multiplying by 0.05).
- Forgetting to subtract discount from total.
"""
        },
        {
            "topic": "Variables & Data Types",
            "title": "Temperature Converter (Celsius to Fahrenheit & Kelvin)",
            "difficulty": "Easy",
            "description": "Write a program that takes temperature in Celsius from the user and converts it into Fahrenheit (F = C * 9/5 + 32) and Kelvin (K = C + 273.15). Display both converted values rounded to 2 decimal places.",
            "sample_input": "Enter temperature in Celsius: 37",
            "sample_output": "37.00°C is equal to:\nFahrenheit : 98.60°F\nKelvin     : 310.15 K",
            "concepts": json.dumps(["float()", "order of operations", "formula calculation", "round() or :.2f"]),
            "starter_code": "celsius = float(input(\"Enter temperature in Celsius: \"))\n# Apply formulas and print\n",
            "ai_rubric": """
VALID APPROACHES:
- fahrenheit = (celsius * 9/5) + 32 or celsius * 1.8 + 32.
- kelvin = celsius + 273.15.
- Both round() and f-string :.2f formatting are acceptable.

COMMON BEGINNER MISTAKES:
- Incorrect operator precedence, e.g. celsius * 9 / (5 + 32).
- Hardcoding values instead of using the user input.
- Missing float conversion on input().
"""
        },

        # Topic 2: Operators & Expressions
        {
            "topic": "Operators & Expressions",
            "title": "Time Breakdown (Seconds to Hours, Mins & Secs)",
            "difficulty": "Medium",
            "description": "Given a total number of seconds as an integer input, convert and display it in Hours, Minutes, and remaining Seconds using integer division (//) and modulus (%) operators.",
            "sample_input": "Enter total seconds: 3665",
            "sample_output": "3665 seconds = 1 Hours, 1 Minutes, and 5 Seconds",
            "concepts": json.dumps(["// operator", "% operator", "int arithmetic"]),
            "starter_code": "total_seconds = int(input(\"Enter total seconds: \"))\n# Calculate hours, minutes, and remaining seconds using // and %\n",
            "ai_rubric": """
VALID APPROACHES:
- Approach 1:
  hours = total_seconds // 3600
  rem = total_seconds % 3600
  minutes = rem // 60
  seconds = rem % 60
- Approach 2:
  minutes_total = total_seconds // 60
  seconds = total_seconds % 60
  hours = minutes_total // 60
  minutes = minutes_total % 60

COMMON BEGINNER MISTAKES:
- Using / (float division) instead of // (floor division), resulting in fractional seconds.
- Forgetting that an hour has 3600 seconds, not 60.
- Reusing variable names incorrectly.
"""
        },
        {
            "topic": "Operators & Expressions",
            "title": "Restaurant Bill & Tip Splitter",
            "difficulty": "Easy",
            "description": "Ask for the food bill amount, tip percentage (e.g. 10 for 10%), and the number of friends sharing the bill. Calculate total tip, total bill with tip, and amount each person must pay. Format each to 2 decimal places.",
            "sample_input": "Enter food bill: 1500\nEnter tip percentage: 10\nEnter number of people: 3",
            "sample_output": "Tip Amount : Rs 150.00\nTotal Bill : Rs 1650.00\nPer Person : Rs 550.00",
            "concepts": json.dumps(["arithmetic operators", "division", "f-strings :.2f"]),
            "starter_code": "# Take input for bill, tip percentage, and number of people\n\n",
            "ai_rubric": """
VALID APPROACHES:
- tip_amount = bill * (tip_percent / 100)
- total_bill = bill + tip_amount
- per_person = total_bill / people

COMMON BEGINNER MISTAKES:
- tip = bill * tip_percent (forgetting / 100).
- Dividing bill by people before adding tip and getting wrong rounding.
- Dividing by zero not handled (acceptable at beginner stage, but praiseworthy if mentioned).
"""
        },

        # Topic 3: Python Math Module
        {
            "topic": "Python Math Module",
            "title": "Room Painting & Flooring Estimator",
            "difficulty": "Medium",
            "description": "A contractor needs to paint the 4 walls of a rectangular room and measure the floor diagonal for tile alignment.\nInputs: room length, width, and height (in meters).\nFormulas:\n1. Total wall area = 2 * height * (length + width)\n2. One can of paint covers 10 sq.m. You CANNOT buy partial cans, so round UP using math.ceil().\n3. Floor diagonal = sqrt(length^2 + width^2) using math.sqrt() and math.pow().\nDisplay wall area (2 decimal places), cans needed (integer), and floor diagonal (2 decimal places).",
            "sample_input": "Enter length (m): 6.5\nEnter width (m): 4.0\nEnter height (m): 3.0",
            "sample_output": "Wall Area     : 63.00 sq m\nCans Required : 7 cans\nFloor Diagonal: 7.63 m",
            "concepts": json.dumps(["import math", "math.ceil()", "math.sqrt()", "math.pow()", ":.2f formatting"]),
            "starter_code": "import math\n\nlength = float(input(\"Enter length (m): \"))\nwidth = float(input(\"Enter width (m): \"))\nheight = float(input(\"Enter height (m): \"))\n\n# Perform calculations using math.ceil and math.sqrt\n",
            "ai_rubric": """
VALID APPROACHES:
- import math at the top.
- wall_area = 2 * height * (length + width)
- cans = math.ceil(wall_area / 10)
- diagonal = math.sqrt(math.pow(length, 2) + math.pow(width, 2)) or math.sqrt(length**2 + width**2) or math.hypot(length, width).

COMMON BEGINNER MISTAKES:
- Using round() or int() instead of math.ceil() for cans (if wall_area is 63, 63/10 is 6.3; int() gives 6, but 6 cans leave 3 sq.m unpainted!).
- Forgetting to import math.
- Incorrect wall area formula (e.g. including floor or ceiling).
"""
        },
        {
            "topic": "Python Math Module",
            "title": "Cylinder Surface Area & Volume Calculator",
            "difficulty": "Medium",
            "description": "Write a program that takes the radius and height of a cylinder from the user and calculates:\n1. Curved Surface Area = 2 * pi * r * h\n2. Total Surface Area = 2 * pi * r * (r + h)\n3. Volume = pi * r^2 * h\nUse math.pi and math.pow() from the math module. Print all results rounded to 2 decimal places.",
            "sample_input": "Enter radius: 5\nEnter height: 12",
            "sample_output": "Curved Surface Area: 376.99\nTotal Surface Area : 534.07\nVolume             : 942.48",
            "concepts": json.dumps(["import math", "math.pi", "math.pow()", "f-string :.2f"]),
            "starter_code": "import math\n\nr = float(input(\"Enter radius: \"))\nh = float(input(\"Enter height: \"))\n\n# Calculate using math.pi and math.pow()\n",
            "ai_rubric": """
VALID APPROACHES:
- Uses math.pi instead of hardcoded 3.14.
- Uses math.pow(r, 2) or r ** 2.
- Formats outputs cleanly with :.2f.

COMMON BEGINNER MISTAKES:
- Using 3.14 or 22/7 instead of math.pi.
- Forgetting parentheses in total surface area: 2 * pi * r * (r + h).
- Confusing curved surface area with total surface area.
"""
        },

        # Topic 4: Decision Making (if / if-else / elif)
        {
            "topic": "Decision Making (if / else)",
            "title": "Voting Eligibility & Remaining Years",
            "difficulty": "Easy",
            "description": "Write a program to ask for the user's age. If the age is 18 or above, print 'Eligible to Vote!'. Otherwise, print 'Not eligible yet.' and calculate and display how many years they must wait until they become eligible.",
            "sample_input": "Enter your age: 15",
            "sample_output": "Not eligible yet.\nYou must wait 3 more year(s) to vote.",
            "concepts": json.dumps(["if-else", "relational operator >=", "subtraction in else block"]),
            "starter_code": "age = int(input(\"Enter your age: \"))\n\n# Check eligibility using if-else\n",
            "ai_rubric": """
VALID APPROACHES:
- if age >= 18: print eligible.
- else: years_left = 18 - age; print wait years_left.
- Can also check if age < 18 first, both are completely valid logic structures.

COMMON BEGINNER MISTAKES:
- Using = instead of == or >=.
- Forgetting colon (:) after if or else.
- Indentation errors in the else block.
- Calculating 18 - age in the if branch instead of the else branch.
"""
        },
        {
            "topic": "Decision Making (if / else)",
            "title": "Student Grade Classifier",
            "difficulty": "Medium",
            "description": "Ask the user to enter their exam marks (0 to 100).\n1. First check if marks are valid (between 0 and 100). If not, print 'Invalid Marks! Must be between 0 and 100.'\n2. If valid, assign grades:\n   - 90 to 100: Grade A+\n   - 80 to 89: Grade A\n   - 70 to 79: Grade B\n   - 60 to 69: Grade C\n   - 40 to 59: Grade D (Pass)\n   - Below 40: Grade F (Fail)",
            "sample_input": "Enter marks: 84",
            "sample_output": "Result: Grade A",
            "concepts": json.dumps(["if-elif-else", "chained comparison", "logical and", "input validation"]),
            "starter_code": "marks = float(input(\"Enter marks (0-100): \"))\n\n# Validate input and assign grade\n",
            "ai_rubric": """
VALID APPROACHES:
- Validate using if marks < 0 or marks > 100: ...
- Then elif marks >= 90: Grade A+
- elif marks >= 80: Grade A (no need for <= 89 because top-down evaluation handles it!)
- Praise student if they realize >= 80 is enough without repeating <= 89.
- Both chained comparisons (80 <= marks <= 89) and pure elif hierarchies are valid.

COMMON BEGINNER MISTAKES:
- Using multiple independent 'if' statements instead of 'elif', causing multiple grades to print!
- Ordering conditions backwards (e.g. checking marks >= 40 first, which triggers for 95 too!).
- Missing validation for negative numbers or marks > 100.
"""
        },
        {
            "topic": "Decision Making (if / else)",
            "title": "Positive, Negative, or Zero with Parity",
            "difficulty": "Easy",
            "description": "Write a program that takes an integer from the user. First, determine whether the number is Positive, Negative, or Zero. If the number is non-zero, also tell whether it is Even or Odd.",
            "sample_input": "Enter an integer: -14",
            "sample_output": "The number is Negative and Even.",
            "concepts": json.dumps(["if-elif-else", "modulus %", "nested if or combined if"]),
            "starter_code": "num = int(input(\"Enter an integer: \"))\n\n# Check sign and parity\n",
            "ai_rubric": """
VALID APPROACHES:
- Check num == 0 first, or check sign first then parity.
- Can use nested conditions or separate variables:
  sign = 'Positive' if num > 0 else 'Negative'
  parity = 'Even' if num % 2 == 0 else 'Odd'
- Multiple approaches are all valid.

COMMON BEGINNER MISTAKES:
- Saying 0 is Positive or Negative.
- Trying to compute parity on 0 (while 0 is mathematically even, saying 'Zero and Even' is clunky unless specified).
- Confusion with negative modulus (in Python -14 % 2 is 0, which works!).
"""
        },

        # Topic 5: Nested Conditions & Logical Operators
        {
            "topic": "Nested Conditions",
            "title": "ATM Cash Withdrawal Simulator",
            "difficulty": "Hard",
            "description": "Simulate an ATM cash withdrawal:\n- Initial account balance is fixed at Rs 25,000.\n- Correct secret PIN is 4321.\nSteps:\n1. Ask the user for their 4-digit PIN.\n2. If PIN is incorrect, print 'Access Denied: Incorrect PIN!'.\n3. If PIN is correct, ask for withdrawal amount.\n4. Check if amount > 0. If not, print 'Error: Withdrawal amount must be positive!'.\n5. Check if amount is a multiple of 100 (ATM dispenses 100/500 notes). If not, print 'Error: Amount must be in multiples of 100!'.\n6. Check if amount <= balance. If yes, deduct and print new balance. If no, print 'Error: Insufficient funds!'.",
            "sample_input": "Enter PIN: 4321\nEnter withdrawal amount: 3500",
            "sample_output": "Transaction Successful!\nWithdrawn  : Rs 3500\nNew Balance: Rs 21500",
            "concepts": json.dumps(["nested if", "modulus % 100", "multiple validations", "state update"]),
            "starter_code": "balance = 25000\nCORRECT_PIN = 4321\n\n# Write nested checks for PIN, positivity, multiples of 100, and balance\n",
            "ai_rubric": """
VALID APPROACHES:
- Nested structure:
  if pin == CORRECT_PIN:
      amount = int(input(...))
      if amount <= 0: ...
      elif amount % 100 != 0: ...
      elif amount > balance: ...
      else: balance -= amount ...
- Early exit or sequential validation structures are all valid.

COMMON BEGINNER MISTAKES:
- Deducting money even when insufficient funds or wrong PIN.
- Checking amount before verifying PIN.
- Forgetting amount % 100 == 0 check.
- Using = instead of == for PIN verification.
"""
        },
        {
            "topic": "Nested Conditions",
            "title": "Gregorian Leap Year Precision Checker",
            "difficulty": "Medium",
            "description": "Write a program to determine if a given year is a Leap Year according to standard calendar rules:\n1. A year is a leap year if it is divisible by 4 AND not divisible by 100.\n2. EXCEPT years divisible by 400 ARE leap years (e.g. 2000 was a leap year, but 1900 was not).\nAsk the user for a year and print whether it is a Leap Year with a brief explanation.",
            "sample_input": "Enter a year: 2024",
            "sample_output": "2024 is a LEAP YEAR! (Divisible by 4 and not a century year)",
            "concepts": json.dumps(["logical and / or", "modulus %", "nested conditions"]),
            "starter_code": "year = int(input(\"Enter a year: \"))\n\n# Check leap year rules\n",
            "ai_rubric": """
VALID APPROACHES:
- Approach 1 (Single combined condition):
  if (year % 400 == 0) or (year % 4 == 0 and year % 100 != 0):
      ...
- Approach 2 (Nested / elif hierarchy):
  if year % 400 == 0: ...
  elif year % 100 == 0: ...
  elif year % 4 == 0: ...
  else: ...

COMMON BEGINNER MISTAKES:
- Only checking year % 4 == 0 (fails for 1900, 2100).
- Incorrect order of checks in elif (checking % 4 before % 100).
- Wrong parentheses in the combined boolean condition.
"""
        },
        {
            "topic": "Nested Conditions",
            "title": "Tiered Electricity Consumption Bill",
            "difficulty": "Hard",
            "description": "Calculate an electricity bill based on units consumed using slab-based pricing:\n- Units <= 100: Rs 4.50 per unit\n- Units 101 to 200: First 100 @ Rs 4.50, remaining @ Rs 6.00 per unit\n- Units 201 to 300: First 100 @ Rs 4.50, next 100 @ Rs 6.00, remaining @ Rs 8.00 per unit\n- Units above 300: First 100 @ Rs 4.50, next 100 @ Rs 6.00, next 100 @ Rs 8.00, remaining @ Rs 10.50 per unit\nA fixed meter surcharge of Rs 50 is added to all bills. Print total units, energy charge, surcharge, and total bill rounded to 2 decimal places.",
            "sample_input": "Enter units consumed: 250",
            "sample_output": "--- ELECTRICITY BILL ---\nUnits Consumed : 250\nEnergy Charges : Rs 1450.00\nMeter Surcharge: Rs 50.00\nTotal Payable  : Rs 1500.00",
            "concepts": json.dumps(["cumulative slab calculation", "if-elif-else", "float calculations", ":.2f"]),
            "starter_code": "units = float(input(\"Enter units consumed: \"))\nSURCHARGE = 50.0\n\n# Calculate slab-wise bill\n",
            "ai_rubric": """
VALID APPROACHES:
- Cumulative slab calculation:
  For units = 250:
  100 * 4.50 + 100 * 6.00 + (250 - 200) * 8.00 = 450 + 600 + 400 = 1450.
- Surcharge of 50 added at the end.

COMMON BEGINNER MISTAKES:
- Flat-rate multiplication instead of slab: e.g. calculating 250 * 8.00 = 2000 (wrong!).
- Forgetting to subtract previous slab boundaries: (units - 100), (units - 200), etc.
- Forgetting the Rs 50 surcharge.
"""
        }
    ]

    for p in problems:
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

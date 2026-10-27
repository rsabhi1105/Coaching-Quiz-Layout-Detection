## Initial setup (only once)
cd books-layout-detection

# Create a virtual environment
python -m venv .venv

# Install required dependencies
.venv/Scripts/python -m pip install -r requirements.txt


Upload a book to the database
# Book upload karni hai (DB me jaati hai) — browser me form khulta hai
.venv/Scripts/python -m books_layout.cli upload


# Sirf parse karke dekhna hai, DB touch nahi
python detection_runner.py                  # file picker + HTML viewer khulta hai

# Health checks
.venv/Scripts/python -m books_layout.cli check-db        # DB connection
.venv/Scripts/python -m books_layout.cli check-platform  # Django models match kar rahe hain

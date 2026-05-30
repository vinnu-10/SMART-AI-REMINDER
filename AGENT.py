import os
# smart_agent_reminder.py

from dotenv import load_dotenv

# This line reads the GEMINI_API_KEY from the .env file and sets it
# as an environment variable in your script's operating system environment.
load_dotenv() 

# Now, the rest of your script, including the client initialization, 
# will automatically find and use the key!
# e.g., client = genai.Client()
# --- STEP 3: Your check will now succeed ---
# Your original code (or similar key checking logic)
if not os.getenv("GEMINI_API_KEY"):
    print("--------------------------------------------------")
    print("FATAL ERROR: The 'GEMINI_API_KEY' environment variable is not set.")
    print("Please set it in your terminal or OS environment before running.")
    # You likely have an 'exit()' or 'sys.exit()' here to stop the program
else:
    # If the key is set, the rest of your program continues...
    # For example:
    # client = genai.Client()
    pass

# ... rest of your codeimport os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from google import genai
from google.genai import types

# -------------------------- CONFIGURATION --------------------------
# !!! IMPORTANT: Replace with your actual Gmail and generated App Password !!!
# See the execution steps for details on generating an App Password.
SENDER_EMAIL = "vmudide@gmail.com"
APP_PASSWORD = "Vinnu@123" 
MODEL = 'gemini-2.5-flash'
# -------------------------------------------------------------------

# --- STEP 1: DEFINE THE TOOL (The Action) ---

def send_email_reminder(recipient_email: str, subject: str, body: str):
    """
    Sends an email reminder using a secure SMTP connection.
    This function is executed by the Python script after the AI calls it.
    """
    if not all([recipient_email, subject, body]):
        print("❌ Error: Missing email details. Cannot send reminder.")
        return

    message = MIMEMultipart()
    message["From"] = SENDER_EMAIL
    message["To"] = recipient_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        # Connect to Gmail's SMTP server on port 587
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()  # Upgrade connection to secure TLS
        server.login(SENDER_EMAIL, APP_PASSWORD)
        
        server.sendmail(SENDER_EMAIL, recipient_email, message.as_string())
        print(f"\n✅ SUCCESS: Email reminder scheduled!")
        print(f"   Recipient: {recipient_email}")
        print(f"   Subject: {subject}")
        print(f"   Body: {body}\n")
        
    except Exception as e:
        print(f"\n❌ ERROR: Failed to send email via SMTP. Check your SENDER_EMAIL/APP_PASSWORD: {e}\n")
    finally:
        if 'server' in locals():
            server.quit()

# --- STEP 2: AI AGENT SETUP (The Brain) ---

REMINDER_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="send_email_reminder",  # Must match the Python function name
            description="Use this tool to create an email reminder with a recipient email, a subject, and the reminder body. ALWAYS call this tool after parsing a reminder request.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "recipient_email": types.Schema(
                        type=types.Type.STRING,
                        description="The recipient's full email address (e.g., 'user@example.com')."
                    ),
                    "subject": types.Schema(
                        type=types.Type.STRING,
                        description="A concise subject line for the reminder email."
                    ),
                    "body": types.Schema(
                        type=types.Type.STRING,
                        description="The full detailed content of the reminder."
                    ),
                },
                required=["recipient_email", "subject", "body"],
            ),
        )
    ]
)

SYSTEM_INSTRUCTION = (
    "You are a Smart Reminder Agent. Your primary function is to analyze the user's text and immediately call the 'send_email_reminder' tool with the extracted details."
    "1. **Extraction**: Extract the recipient email, a subject, and the detailed body of the reminder."
    "2. **Default**: If the user does not explicitly mention an email, use 'me@default.com' as the recipient."
    "3. **Format**: The final output must be a tool call, never a conversational response. Do not output anything other than the tool call."
    f"Current date and time is: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
)

# --- STEP 3: AGENT EXECUTION LOGIC ---

def run_agent(prompt: str):
    """
    Executes the interaction with the Gemini model.
    """
    try:
        client = genai.Client()
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize Gemini Client. Check GEMINI_API_KEY environment variable. Details: {e}")
        return

    print(f"User Prompt: \"{prompt}\"")
    print("🤖 Agent thinking...")
    
    # 1. First API Call: Send prompt and tools to the model
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=[REMINDER_TOOL]
        )
    )

    # 2. Check for a Tool Call
    if not response.function_calls:
        print(f"⚠️ Warning: Agent did not call a function. Model's text response: {response.text}")
        return

    # 3. Process the Tool Call
    tool_call = response.function_calls[0]
    func_name = tool_call.name
    func_args = dict(tool_call.args)

    if func_name == "send_email_reminder":
        # Execute the corresponding Python function with the arguments from the AI
        send_email_reminder(**func_args)
    else:
        print(f"❌ Error: Unknown function call '{func_name}'")


if __name__ == "__main__":
    print("-" * 50)
    # --- PRE-FLIGHT CHECKS ---
    if not os.getenv("GEMINI_API_KEY"):
        print("FATAL ERROR: The 'GEMINI_API_KEY' environment variable is not set.")
        print("Please set it in your terminal or OS environment before running.")
    elif SENDER_EMAIL == "your_email@gmail.com" or APP_PASSWORD == "YOUR_APP_PASSWORD":
        print("FATAL ERROR: Please update SENDER_EMAIL and APP_PASSWORD in the code with your actual credentials.")
    else:
        # --- EXECUTION ---
        # Example Prompt 1: Default recipient used
        USER_PROMPT_1 = "Remind me next Monday at 10 AM to start the new marketing campaign."
        run_agent(USER_PROMPT_1) 
        
        print("-" * 50)
        
        # Example Prompt 2: Explicit recipient and details provided
        USER_PROMPT_2 = "Send a quick note to sally@company.com with the subject 'Project Alpha Status' and the body 'Please update the shared doc with your progress by EOD.'"
        run_agent(USER_PROMPT_2)
    print("-" * 50)

import os
import json
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import google.generativeai as genai
from googleapiclient.discovery import build

# --- 1. INITIAL SETUP & CONFIGURATIONS ---
load_dotenv()
app = Flask(__name__)

# API Configurations
try:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") # For Google Drive
    
    if not GEMINI_API_KEY or not GITHUB_TOKEN or not GOOGLE_API_KEY:
        raise ValueError("One or more API keys are missing from environment variables.")
        
    genai.configure(api_key=GEMINI_API_KEY)
except Exception as e:
    print(f"Error during initial configuration: {e}")

# --- 2. HELPER FUNCTIONS (EVIDENCE GATHERING) ---

def get_github_repo_contents(repo_url: str) -> list:
    """Fetches the list of files from a GitHub repository URL using the API."""
    print(f"HELPER: Fetching content from GitHub URL: {repo_url}")
    try:
        parts = repo_url.strip('/').split('/')
        owner, repo = parts[-2], parts[-1]
        # --- FIX: Remove .git suffix if it exists ---
        if repo.endswith('.git'):
            repo = repo[:-4]
        # -------------------------------------------
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        return [item['name'] for item in response.json()]
    except Exception as e:
        print(f"Error fetching GitHub contents: {e}")
        return None

def get_google_drive_folder_contents(folder_url: str) -> list:
    """Fetches the list of files from a public Google Drive folder."""
    print(f"HELPER: Fetching content from Google Drive URL: {folder_url}")
    try:
        folder_id = folder_url.split('/')[-1].split('?')[0]
        service = build('drive', 'v3', developerKey=GOOGLE_API_KEY)
        query = f"'{folder_id}' in parents"
        results = service.files().list(q=query, fields="files(name)").execute()
        return [item['name'] for item in results.get('files', [])]
    except Exception as e:
        print(f"Error fetching Google Drive contents: {e}")
        return None

def scrape_website_text(url: str) -> str:
    """Fetches and extracts all visible text from a live website URL."""
    print(f"HELPER: Scraping content from Vercel/Web URL: {url}")
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        for script in soup(["script", "style"]): script.extract()
        return " ".join(soup.stripped_strings)
    except requests.RequestException as e:
        print(f"Error scraping URL {url}: {e}")
        return None

# --- 3. CORE AI LOGIC (GEMINI) ---

def _classify_freelancer_role(contract_details: dict) -> str:
    """AI Step 1: Deduces the freelancer's role from the contract text."""
    print("--- AI Step 1: Classifying Freelancer Role ---")
    try:
        # ... (This function's code remains the same as the previous version) ...
        project_description = contract_details.get("projectDescription", "")
        tasks = "\n- ".join(contract_details.get("task", []))
        prompt = f"""Analyze the following contract details and classify the freelancer's role into ONE of these categories: "UI/UX Designer", "Graphic Designer", "Web Developer", "Content Writer", "Social Media Manager". Respond with only the category name."""
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(f"{prompt}\n\n**Contract Details:**\n- Project Description: {project_description}\n- Tasks: {tasks}")
        role = response.text.strip().replace('"', '')
        print(f"AI Classified Role as: {role}")
        return role
    except Exception as e:
        print(f"Error in AI role classification: {e}")
        return "Unknown"

def _verify_proof_with_role(contract_details: dict, evidence: any, evidence_type: str, freelancer_role: str) -> dict:
    """AI Step 2: Verifies the gathered evidence based on the deduced role."""
    print(f"--- AI Step 2: Verifying {evidence_type} for a {freelancer_role} ---")
    
    prompt_template = """
    You are an AI dispute resolution agent. Your task is to analyze the provided proof against the contract requirements. Your goal is to determine if the proof is a PLAUSIBLE match for the work described.

    **Contract Requirements:**
    - Project Description: {project_description}
    - Tasks: {tasks}

    **Evidence Provided ({evidence_type}):**
    {evidence}

    **Your Analysis:**
    Based on the evidence, is it plausible that the work described has been completed?

    **Respond in JSON format with two keys:**
    1. "decision": Must be "approved" or "needs_review".
    2. "justification": A brief, one-sentence explanation.
    """
    
    final_prompt = prompt_template.format(
        freelancer_role=freelancer_role,
        project_description=contract_details.get("projectDescription", ""),
        tasks="\n- ".join(contract_details.get("task", [])),
        evidence_type=evidence_type,
        evidence=str(evidence)
    )

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(final_prompt)
        json_response_str = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(json_response_str)
    except Exception as e:
        return {"decision": "error", "justification": f"Gemini API error: {e}"}

def get_ai_dispute_verdict(contract_details: dict) -> dict:
    """Performs the full two-step AI check using the best available proof."""
    freelancer_role = _classify_freelancer_role(contract_details)
    if freelancer_role == "Unknown":
        return {"status": "not accepted", "reason": "Could not determine freelancer role from contract."}
    
    links = contract_details.get("links", [])
    if not links:
        return {"status": "not accepted", "reason": "No proof links were provided."}

    # Prioritize the first link for analysis
    proof_url = links[0]
    evidence = None
    evidence_type = "Unknown"

    # Select the correct helper function based on the URL
    if "github.com" in proof_url:
        evidence = get_github_repo_contents(proof_url)
        evidence_type = "List of Files from GitHub"
    elif "drive.google.com" in proof_url:
        evidence = get_google_drive_folder_contents(proof_url)
        evidence_type = "List of Files from Google Drive"
    else: # Assume it's a live website (Vercel, etc.)
        evidence = scrape_website_text(proof_url)
        evidence_type = "Scraped Website Content"

    if not evidence:
        return {"status": "not accepted", "reason": f"Could not access or process the proof from the provided link: {proof_url}"}

    ai_detailed_verdict = _verify_proof_with_role(contract_details, evidence, evidence_type, freelancer_role)
    
    decision = ai_detailed_verdict.get("decision")
    justification = ai_detailed_verdict.get("justification")

    if decision == "approved":
        return {"status": "accepted", "reason": justification}
    else:
        return {"status": "not accepted", "reason": justification}

# --- 4. FLASK API ENDPOINT FOR PRODUCTION ---

@app.route("/verify-proof", methods=["POST"])
def handle_dispute():
    """Production endpoint. Accepts a JSON body with contract and proof details."""
    try:
        body = request.json
        contract_details = body.get("contractData")

        if not contract_details:
            return jsonify({"ok": False, "error": "Missing 'contractData' in request body."}), 400

        print("Received dispute request. Submitting to AI for verification...")
        ai_verdict = get_ai_dispute_verdict(contract_details)
        print(f"Final AI Verdict: {ai_verdict}")

        return jsonify({
            "ok": True,
            "status": ai_verdict.get("status"),
            "reason": ai_verdict.get("reason")
        })

    except Exception as e:
        print(f"An unexpected error occurred in the endpoint: {e}")
        return jsonify({"ok": False, "error": "An internal server error occurred."}), 500

if __name__ == "__main__":
    app.run(debug=True, port=8080)


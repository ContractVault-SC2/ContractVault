import os
import pdfkit
import base64
import requests
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="templates")

# wkhtmltopdf binary path
WKHTMLTOPDF_PATH = "/usr/bin/wkhtmltopdf"
config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)

# PDF options
PDF_OPTIONS = {
    "enable-local-file-access": None,
    "load-error-handling": "ignore",
    "load-media-error-handling": "ignore",
    "no-stop-slow-scripts": None,
    "javascript-delay": "8000",
    "disable-smart-shrinking": None
}

# GitHub setup
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")  # e.g. "NilanjanSaha-K/ContractVault"
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")








def img_to_base64(path):
    """Convert local image file to base64 data URI"""
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("utf-8")


def upload_to_github(file_path, file_name):
    """Upload file to GitHub, overwrite if exists"""
    print(f"--- Starting GitHub upload for {file_name} ---")
    with open(file_path, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_name}?t={int(time.time())}"  # Add timestamp to avoid caching issues
    headers = {"Authorization": f"token {GITHUB_TOKEN}"} 

    # --- Step 1: Check if file exists and get its SHA ---
    sha = None
    print(f"Checking for existing file at: {url}")
    r = requests.get(url, headers=headers, params={"ref": GITHUB_BRANCH})
    
    print(f"GET request status code: {r.status_code}")
    if r.status_code == 200:
        sha = r.json().get("sha")
        print(f"File exists. SHA received: {sha}")
    else:
        print("File does not exist or failed to fetch. Will attempt to create a new file.")
        print(f"GET response body: {r.text}")


    # --- Step 2: Prepare the payload for the PUT request ---
    payload = {
        "message": f"Update contract {file_name}",
        "content": content,
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha # Add SHA to payload if we are updating

    print(f"Preparing to send PUT request. Payload includes SHA: {'sha' in payload}")

    # --- Step 3: Send the PUT request to create or update the file ---
    response = requests.put(url, headers=headers, json=payload)
    
    print(f"GitHub PUT response status: {response.status_code}")
    print(f"GitHub PUT response body: {response.text}")

    if response.status_code in [200, 201]:
        print("--- Upload successful! ---")
        return f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{file_name}"
    else:
        # Raise an exception with a more detailed error message
        error_message = response.json().get('message', response.text)
        raise Exception(f"GitHub upload failed with status {response.status_code}: {error_message}")


@app.route("/create-contract", methods=["POST"])
def create_contract():
    try:
        body = request.json

        # Map JSON → template vars
        mapped_data = {
            "contractId": body.get("contractId"),
            "date": body.get("currentDate"),
            "freelancer_name": body.get("fullName_freelancer"),
            "freelancer_email": body.get("userEmail"),
            "client_name": body.get("fullName_client"),
            "client_email": body.get("clientEmail"),
            "agency_name": body.get("agencyName"),
            "project_description": body.get("contractData", {}).get("projectDescription"),
            "clauses": body.get("contractData", {}).get("task", []),
            "end_date": body.get("contractData", {}).get("DeadLine"),
            "total_amount": f"{body.get('contractData', {}).get('totalAmount','')} {body.get('contractData', {}).get('currency','')}",
        }

        # Logo → Base64
       

        # Signatures (either external URLs or local files → base64)
        sig_user = body.get("signatureUser")
        sig_client = body.get("signatureClient")

        if sig_user and os.path.exists(sig_user):
            mapped_data["signatureUser"] = img_to_base64(sig_user)
        else:
            mapped_data["signatureUser"] = sig_user

        if sig_client and os.path.exists(sig_client):
            mapped_data["signatureClient"] = img_to_base64(sig_client)
        else:
            mapped_data["signatureClient"] = sig_client

        # Render HTML
        html = render_template("contract.html", **mapped_data)

        # Save PDF locally
        file_name = f"{mapped_data['contractId']}.pdf"
        file_path = os.path.join(os.getcwd(), file_name)
        pdfkit.from_string(html, file_path, configuration=config, options=PDF_OPTIONS)

        # Upload to GitHub
        github_url = upload_to_github(file_path, file_name)

        return jsonify({"ok": True, "url": github_url})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

import time # Add this import at the top of your file

# ... (keep the rest of your code the same)

@app.route("/isAccepted", methods=["POST"])
def accept_contract():
    try:
        body = request.json
        print("\n--- Received request for /isAccepted ---")
        print(f"Client Signature URL from JSON: {body.get('signatureClient')}")

        if not body.get("signatureClient"):
            return jsonify({"ok": False, "error": "Client signature is missing"}), 400

        # 1. Map all the data again
        mapped_data = {
            "contractId": body.get("contractId"),
            "date": body.get("currentDate"),
            "freelancer_name": body.get("fullName_freelancer"),
            "freelancer_email": body.get("userEmail"),
            "client_name": body.get("fullName_client"),
            "client_email": body.get("clientEmail"),
            "agency_name": body.get("agencyName"),
            "project_description": body.get("contractData", {}).get("projectDescription"),
            "clauses": body.get("contractData", {}).get("task", []),
            "end_date": body.get("contractData", {}).get("DeadLine"),
            "total_amount": f"{body.get('contractData', {}).get('totalAmount','')} {body.get('contractData', {}).get('currency','')}",
        }

        # 2. Process logo and signatures reliably
        # Logo
        logo_path = os.path.join(app.static_folder, "logo.png")
        mapped_data["logo_base64"] = img_to_base64(logo_path) if os.path.exists(logo_path) else None

        # Signatures (with robust URL downloading)
        sig_user_url = body.get("signatureUser")
        sig_client_url = body.get("signatureClient")
        mapped_data["signatureUser"] = None
        mapped_data["signatureClient"] = None

        try:
            if sig_user_url and sig_user_url.startswith('http'):
                response = requests.get(sig_user_url)
                response.raise_for_status()
                b64_img = base64.b64encode(response.content).decode("utf-8")
                mapped_data["signatureUser"] = f"data:image/png;base64,{b64_img}"

            if sig_client_url and sig_client_url.startswith('http'):
                print(">>> Downloading Client Signature...")
                response = requests.get(sig_client_url)
                response.raise_for_status()
                b64_img = base64.b64encode(response.content).decode("utf-8")
                mapped_data["signatureClient"] = f"data:image/png;base64,{b64_img}"
                print(">>> Client Signature processed successfully.")

        except requests.exceptions.RequestException as e:
            return jsonify({"ok": False, "error": f"Failed to download signature image: {e}"}), 500

        # 3. Render HTML and SAVE IT to a temporary file
        html = render_template("contract.html", **mapped_data)
        
        # --- DEBUGGING STEP: Check if the signature is in the HTML before PDF conversion ---
        if mapped_data["signatureClient"]:
             print(">>> VERIFICATION: Client signature IS IN the HTML string.")
        else:
             print(">>> VERIFICATION: Client signature IS NOT in the HTML string.")

        temp_html_path = f"temp_{mapped_data['contractId']}_{int(time.time())}.html"
        with open(temp_html_path, "w", encoding="utf-8") as f:
            f.write(html)

        # 4. Generate the PDF from the temporary HTML FILE
        file_name = f"{mapped_data['contractId']}.pdf"
        file_path = os.path.join(os.getcwd(), file_name)
        print(f">>> Generating PDF from temporary file: {temp_html_path}")
        pdfkit.from_file(temp_html_path, file_path, configuration=config, options=PDF_OPTIONS)

        # 5. Clean up the temporary HTML file
        os.remove(temp_html_path)

        # 6. Re-upload to GitHub
        github_url = upload_to_github(file_path, file_name)

        return jsonify({"ok": True, "message": "Contract accepted and updated.", "url": github_url})

    except Exception as e:
        # Clean up temp file in case of an error
        if 'temp_html_path' in locals() and os.path.exists(temp_html_path):
            os.remove(temp_html_path)
        print(f"An error occurred: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
if __name__ == "__main__":
    app.run(debug=True, port=8080)


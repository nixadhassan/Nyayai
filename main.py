import io
import os
import base64
from fastapi import FastAPI, UploadFile, File, HTTPException, Header
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import pypdf
import anthropic
from supabase import create_client

app = FastAPI(title="NYAY AI Professional Legal Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Clients
supabase_client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

def extract_text_from_pdf(file_bytes: bytes) -> str:
    pdf_file = io.BytesIO(file_bytes)
    reader = pypdf.PdfReader(pdf_file)
    return "\n".join([page.extract_text() or "" for page in reader.pages])

@app.post("/api/analyze")
async def analyze_document(files: list[UploadFile] = File(...), authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Please login.")
    
    user_id = authorization.split(" ")[1]
    
    try:
        # Check credits
        db_query = supabase_client.table("users").select("credits_used").eq("id", user_id).execute()
        user_records = db_query.data
        
        if not user_records:
            supabase_client.table("users").insert({"id": user_id, "credits_used": 0}).execute()
            current_usage = 0
        else:
            current_usage = user_records[0]["credits_used"]

        if current_usage >= 2:
            return {"status": "PAYWALL_TRIGGERED", "message": "Free limit reached."}

        # Build Context
        content_list = []
        
        # 1. Legal Knowledge Base Injection
        legal_context = """
        LEGAL KNOWLEDGE BASE FOR INDIAN LAW: 
        - Rental Agreements: Require notice periods, maintenance responsibilities, and clear security deposit terms.
        - Sale Deeds: Must reference Transfer of Property Act, clear title, and full consideration amounts.
        - General: Always check for Stamp Duty, Registration, and Witness signatures.
        """
        content_list.append({"type": "text", "text": legal_context})

        # 2. Document Data Injection
        for file in files:
            file_bytes = await file.read()
            if file.filename.lower().endswith('.pdf'):
                content_list.append({"type": "text", "text": f"--- {file.filename} ---\n{extract_text_from_pdf(file_bytes)}"})
            elif file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                encoded_image = base64.b64encode(file_bytes).decode("utf-8")
                content_list.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": encoded_image}})

        # 3. Structured Prompting with Citation Constraints
        prompt = """
        Act as an expert Indian Advocate. Perform a two-step analysis:
        STEP 1: Identify Parties, Document Type, Dates, and Consideration.
        STEP 2: Risk Assessment. For every risk identified, you MUST provide a "Citation": "Quote from document" to support your claim. 
        Flag any 'Critical Omissions' regarding mandatory Indian legal clauses.
        Output in structured professional markdown.
        """
        content_list.append({"type": "text", "text": prompt})

        # Call Claude
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=2000,
            temperature=0.1,
            messages=[{"role": "user", "content": content_list}]
        )
        
        # Update usage
        supabase_client.table("users").update({"credits_used": current_usage + 1}).eq("id", user_id).execute()
        
        return {"status": "SUCCESS", "analysis": response.content[0].text, "remaining_free": max(0, 2 - (current_usage + 1))}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

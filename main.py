import io
import os
import base64
from fastapi import FastAPI, UploadFile, File, HTTPException, Header
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import pypdf
import anthropic
from supabase import create_client

app = FastAPI(title="NYAY AI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Supabase without legacy 'proxies' arguments
supabase_client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

def extract_text_from_pdf(file_bytes: bytes) -> str:
    pdf_file = io.BytesIO(file_bytes)
    reader = pypdf.PdfReader(pdf_file)
    text = "\n".join([page.extract_text() or "" for page in reader.pages])
    return text

@app.post("/api/analyze")
async def analyze_document(files: list[UploadFile] = File(...), authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Please login first.")
    
    user_id = authorization.split(" ")[1]
    
    try:
        # Check current usage
        db_query = supabase_client.table("users").select("credits_used").eq("id", user_id).execute()
        user_records = db_query.data
        
        if not user_records:
            # FIX: Use 'returning="minimal"' to avoid row-level selection errors
            supabase_client.table("users").insert({"id": user_id, "credits_used": 0}).execute()
            current_usage = 0
        else:
            current_usage = user_records[0]["credits_used"]

        if current_usage >= 2:
            return {"status": "PAYWALL_TRIGGERED", "message": "Free limit reached."}

        # Build payload
        content_list = []
        combined_pdf_text = ""
        for file in files:
            file_bytes = await file.read()
            if file.filename.lower().endswith('.pdf'):
                combined_pdf_text += f"\n--- {file.filename} ---\n{extract_text_from_pdf(file_bytes)}"
            elif file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                encoded_image = base64.b64encode(file_bytes).decode("utf-8")
                content_list.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": encoded_image}})

        if combined_pdf_text.strip():
            content_list.append({"type": "text", "text": f"Extracted text: {combined_pdf_text}"})
        
        content_list.append({"type": "text", "text": "Analyze these as an Indian legal expert. Provide 1. Summary, 2. Obligations, 3. Risks, 4. Actions."})

        # Call Claude
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=2000,
            messages=[{"role": "user", "content": content_list}]
        )
        
        # Update usage
        new_usage = current_usage + 1
        supabase_client.table("users").update({"credits_used": new_usage}).eq("id", user_id).execute()
        
        return {"status": "SUCCESS", "analysis": response.content[0].text, "remaining_free": max(0, 2 - new_usage)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

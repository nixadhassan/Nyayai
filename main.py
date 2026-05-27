import io
import os
import base64
from fastapi import FastAPI, UploadFile, File, HTTPException, Header
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import pypdf
import anthropic
from supabase import create_client, Client

app = FastAPI(title="NYAY AI Multi-File Production Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CLAUDE_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not all([CLAUDE_API_KEY, SUPABASE_URL, SUPABASE_KEY]):
    raise RuntimeError("CRITICAL ERROR: Missing backend cloud environment variables!")

anthropic_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def extract_text_from_pdf(file_bytes: bytes) -> str:
    pdf_file = io.BytesIO(file_bytes)
    reader = pypdf.PdfReader(pdf_file)
    text = ""
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            text += extracted + "\n"
    return text

@app.get("/")
def home():
    return {"status": "NYAY AI Backend is running successfully online!"}

@app.post("/api/analyze")
async def analyze_document(
    files: list[UploadFile] = File(...), 
    authorization: str = Header(None)
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Please login first.")
    
    user_id = authorization.split(" ")[1]
    
    try:
        # 1. Query Supabase for credit tracking
        db_query = supabase_client.table("users").select("*").eq("id", user_id).execute()
        user_records = db_query.data
        
        if not user_records:
            current_usage = 0
            supabase_client.table("users").insert({"id": user_id, "credits_used": 0}).execute()
        else:
            current_usage = user_records[0]["credits_used"]

        if current_usage >= 2:
            return {"status": "PAYWALL_TRIGGERED", "message": "Free limit reached."}

        # 2. Build Multimodal Content Payload for Claude API
        content_list = []
        combined_pdf_text = ""

        for file in files:
            file_bytes = await file.read()
            filename_lower = file.filename.lower()

            if filename_lower.endswith('.pdf'):
                text = extract_text_from_pdf(file_bytes)
                combined_pdf_text += f"\n--- Extracted Text from {file.filename} ---\n{text}\n"
            
            elif filename_lower.endswith(('.png', '.jpg', '.jpeg', '.webp')):
                encoded_image = base64.b64encode(file_bytes).decode("utf-8")
                
                media_type = "image/jpeg"
                if filename_lower.endswith('.png'): media_type = "image/png"
                elif filename_lower.endswith('.webp'): media_type = "image/webp"

                content_list.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": encoded_image
                    }
                })
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.filename}")

        if combined_pdf_text.strip():
            content_list.append({
                "type": "text",
                "text": f"Here is text extracted from matching uploaded document templates:\n{combined_pdf_text}"
            })

        # Append the core legal instruction prompt matrix
        content_list.append({
            "type": "text",
            "text": "Analyze the provided legal items (images and/or documents). Provide a clear, structured analysis containing: 1. Executive Summary, 2. Key Obligations, 3. Critical Red Flags/Risks under Indian Law, and 4. Actionable Recommendations. Use clean bullet points and clear headings."
        })

        if not content_list or len(content_list) <= 1:
            raise HTTPException(status_code=400, detail="No readable content or images were uploaded.")

        # 3. Fire request to Claude Multi-Modal Vision Engine
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=2000,
            temperature=0.1,
            system="You are NYAY AI, an expert senior advocate and deed writer assistant in India.",
            messages=[
                {"role": "user", "content": content_list}
            ]
        )
        
        analysis_result = response.content[0].text
        
        # 4. Save consumption credit incrementation
        new_usage = current_usage + 1
        supabase_client.table("users").update({"credits_used": new_usage}).eq("id", user_id).execute()
        remaining_free = max(0, 2 - new_usage)
        
        return {
            "status": "SUCCESS", 
            "analysis": analysis_result, 
            "remaining_free": remaining_free
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"System Error: {str(e)}")

@app.post("/api/generate-pdf")
async def generate_pdf(data: dict):
    analysis_text = data.get("analysis", "")
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, spaceAfter=20, textColor="#1e3a8a")
    body_style = ParagraphStyle('BodyStyle', parent=styles['BodyText'], fontSize=10, leading=14, spaceAfter=10)

    story.append(Paragraph("<b>NYAY AI - LEGAL ANALYSIS REPORT</b>", title_style))
    story.append(Spacer(1, 10))

    for para in analysis_text.split("\n"):
        if para.strip():
            clean_para = para.replace("**", "<b>").replace("**", "</b>").replace("* ", "• ")
            story.append(Paragraph(clean_para, body_style))
            
    doc.build(story)
    pdf_buffer.seek(0)

    return StreamingResponse(
        pdf_buffer, 
        media_type="application/pdf", 
        headers={"Content-Disposition": "attachment; filename=NYAY_AI_Analysis.pdf"}
        )

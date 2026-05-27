import io
import os
from fastapi import FastAPI, UploadFile, File, HTTPException, Header
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import pypdf
import anthropic

app = FastAPI(title="NYAY AI Production Backend")

# Allows your frontend HTML to talk to this backend once deployed online
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Securely fetches the API key from Render's Environment Variables
CLAUDE_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Safety check: Stop the server immediately if you forgot to add the key to Render
if not CLAUDE_API_KEY:
    raise RuntimeError("CRITICAL ERROR: ANTHROPIC_API_KEY environment variable is not set!")

anthropic_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

# In-Memory database for credit tracking
USER_DATABASE = {}

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
    file: UploadFile = File(...), 
    authorization: str = Header(None)
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Please login first.")
    
    user_id = authorization.split(" ")[1]
    
    if user_id not in USER_DATABASE:
        USER_DATABASE[user_id] = 0
        
    current_usage = USER_DATABASE[user_id]
    if current_usage >= 2:
        return {"status": "PAYWALL_TRIGGERED", "message": "Free limit reached."}

    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    try:
        file_bytes = await file.read()
        document_text = extract_text_from_pdf(file_bytes)
        
        if not document_text.strip():
            raise HTTPException(status_code=400, detail="PDF is empty or scanned as an image.")

        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=2000,
            temperature=0.1,
            system="You are NYAY AI, an expert senior advocate and deed writer assistant in India. "
                   "Analyze the provided legal text. Provide a clear, structured analysis containing: "
                   "1. Executive Summary, 2. Key Obligations, 3. Critical Red Flags/Risks under Indian Law, "
                   "and 4. Actionable Recommendations. Use clean bullet points and clear headings.",
            messages=[
                {"role": "user", "content": f"Analyze this legal document:\n\n{document_text}"}
            ]
        )
        
        analysis_result = response.content[0].text
        USER_DATABASE[user_id] += 1
        remaining_free = max(0, 2 - USER_DATABASE[user_id])
        
        return {
            "status": "SUCCESS", 
            "analysis": analysis_result, 
            "remaining_free": remaining_free
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

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
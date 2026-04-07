"""
Resume Tailor Agent
Uses Claude claude-opus-4-6 with adaptive thinking to tailor the resume
for each specific job description.
"""
import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from agents.job_fetcher import JobListing
from utils.logger import get_logger

logger = get_logger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

TAILOR_SYSTEM_PROMPT = """You are an expert resume writer and career coach specializing in
technology roles. Your task is to tailor a candidate's resume to match a specific job description
while keeping all information truthful and accurate.

Guidelines:
- Reorder and emphasize skills/experience that match the job requirements
- Use keywords from the job description naturally throughout the resume
- Strengthen bullet points to highlight relevant achievements
- Keep the same factual content — never fabricate experience or skills
- Maintain professional tone and formatting
- Focus on quantifiable achievements where possible
- Mirror the language and terminology used in the job posting
- Ensure ATS (Applicant Tracking System) optimization with relevant keywords"""


def tailor_resume(resume_text: str, job: JobListing) -> str:
    """
    Use Claude to tailor the resume text for a specific job listing.
    Returns the tailored resume as plain text.
    """
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "your_anthropic_api_key_here":
        logger.error("ANTHROPIC_API_KEY not configured.")
        return resume_text

    prompt = f"""Please tailor the following resume for this specific job posting.

## JOB DETAILS
**Title:** {job.title}
**Company:** {job.company}
**Location:** {job.location}
**Job Description:**
{job.description[:3000]}

## ORIGINAL RESUME
{resume_text}

## INSTRUCTIONS
1. Rewrite the resume to best match this job description
2. Emphasize the most relevant skills, technologies, and experiences
3. Use keywords from the job description
4. Keep all facts accurate — do not invent experience
5. Output ONLY the tailored resume text, ready to copy into a document
6. Format with clear sections (Summary, Experience, Skills, Education)
7. Use action verbs and quantify achievements where possible

Provide the complete tailored resume:"""

    try:
        with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=TAILOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            tailored = stream.get_final_message()

        result_text = ""
        for block in tailored.content:
            if block.type == "text":
                result_text = block.text
                break

        logger.info(f"Resume tailored for: {job.title} @ {job.company}")
        return result_text

    except anthropic.APIError as e:
        logger.error(f"Claude API error while tailoring resume: {e}")
        return resume_text


def analyze_job_fit(resume_text: str, job: JobListing) -> dict:
    """
    Ask Claude to score how well the resume matches the job (0-100)
    and return key missing skills/keywords.
    """
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "your_anthropic_api_key_here":
        return {"score": 50, "missing_skills": [], "matching_skills": [], "recommendation": "API key not set"}

    prompt = f"""Analyze how well this resume matches the job description.

## JOB: {job.title} at {job.company}
{job.description[:2000]}

## RESUME
{resume_text[:2000]}

Respond in this exact JSON format:
{{
  "match_score": <0-100>,
  "matching_skills": ["skill1", "skill2"],
  "missing_skills": ["skill1", "skill2"],
  "recommendation": "brief recommendation",
  "should_apply": true/false
}}"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        text = next((b.text for b in response.content if b.type == "text"), "{}")
        # Extract JSON from response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception as e:
        logger.error(f"Job fit analysis error: {e}")

    return {"score": 50, "missing_skills": [], "matching_skills": [], "recommendation": "Analysis failed", "should_apply": True}

"""
Resume Tailor Agent
Uses Google Gemini (free) to tailor the resume for each specific job description.
Falls back gracefully if GEMINI_API_KEY is not set.
"""
import json

import google.generativeai as genai

from config import GEMINI_API_KEY, GEMINI_MODEL
from agents.job_fetcher import JobListing
from utils.logger import get_logger

logger = get_logger(__name__)

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


def _get_client():
    if not GEMINI_API_KEY:
        return None
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=TAILOR_SYSTEM_PROMPT,
    )


def tailor_resume(resume_text: str, job: JobListing) -> str:
    """
    Use Gemini to tailor the resume text for a specific job listing.
    Returns the tailored resume as plain text.
    Falls back to original resume if API is unavailable.
    """
    client = _get_client()
    if client is None:
        logger.warning("GEMINI_API_KEY not set — using original resume.")
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
        response = client.generate_content(prompt)
        result_text = response.text.strip()
        logger.info(f"Resume tailored for: {job.title} @ {job.company}")
        return result_text
    except Exception as e:
        logger.error(f"Gemini API error while tailoring resume: {e}")
        return resume_text


def analyze_job_fit(resume_text: str, job: JobListing) -> dict:
    """
    Use Gemini to score how well the resume matches the job (0-100).
    Returns a dict with score, matching/missing skills, recommendation.
    """
    client = _get_client()
    if client is None:
        return {"score": 50, "missing_skills": [], "matching_skills": [],
                "recommendation": "API key not set", "should_apply": True}

    prompt = f"""Analyze how well this resume matches the job description.

## JOB: {job.title} at {job.company}
{job.description[:2000]}

## RESUME
{resume_text[:2000]}

Respond in this exact JSON format only, no extra text:
{{
  "match_score": <0-100>,
  "matching_skills": ["skill1", "skill2"],
  "missing_skills": ["skill1", "skill2"],
  "recommendation": "brief recommendation",
  "should_apply": true
}}"""

    try:
        response = client.generate_content(prompt)
        text = response.text.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception as e:
        logger.error(f"Job fit analysis error: {e}")

    return {"score": 50, "missing_skills": [], "matching_skills": [],
            "recommendation": "Analysis failed", "should_apply": True}

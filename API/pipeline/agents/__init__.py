"""Multi-agent pipeline cho sinh MCQ Toán.

Kiến trúc 8 agents (refactor theo papers — see docs/):

    IngestionAgent       — PDF → chunked dataset
    PlannerAgent         — LLM-driven concept + slot inference (Savaal+MCQG-SRefine)
    QuestionWriterAgent  — Stage 1: stem + answer + reasoning (CoE 3-stage)
    DistractorAgent      — Stage 2: distractor gắn misconception (EMNLP-2024 KNN)
    VerifierAgent        — Symbolic verify + natural→SymPy translation
    CriticAgent          — Multi-trait rubric (rationale-before-score, RMTS NAACL-2025)
    RefinerAgent         — Iterative critique→correction (MCQG-SRefine)
    FormatterAgent       — Final question record + shuffle options
    RendererAgent        — Visual spec → PNG/markdown

"""
from .orchestrator import OrchestratorAgent
from .ingestion_agent import IngestionAgent
from .planner_agent import PlannerAgent
from .writer_agent import QuestionWriterAgent
from .question_generator_agent import QuestionGeneratorAgent
from .distractor_agent import DistractorAgent
from .verifier_agent import VerifierAgent
from .critic_agent import CriticAgent
from .refiner_agent import RefinerAgent
from .formatter_agent import FormatterAgent
from .renderer_agent import RendererAgent
from .messages import (
    IngestionRequest, IngestionResponse,
    PlanRequest, PlanResponse,
    GenerateRequest, GenerateResponse,
    WriteRequest, WriteResponse,
    DistractorRequest, DistractorResponse,
    RefineRequest, RefineResponse,
    VerifyRequest, VerifyResponse,
    CriticRequest, CriticResponse,
    FormatAcceptedRequest, FormatRejectedRequest, FormatResponse,
    RenderRequest, RenderResponse,
    SlotResult,
)

__all__ = [
    'OrchestratorAgent',
    'IngestionAgent',
    'PlannerAgent',
    'QuestionWriterAgent',
    'QuestionGeneratorAgent',
    'DistractorAgent',
    'VerifierAgent',
    'CriticAgent',
    'RefinerAgent',
    'FormatterAgent',
    'RendererAgent',
    'IngestionRequest', 'IngestionResponse',
    'PlanRequest', 'PlanResponse',
    'GenerateRequest', 'GenerateResponse',
    'WriteRequest', 'WriteResponse',
    'DistractorRequest', 'DistractorResponse',
    'RefineRequest', 'RefineResponse',
    'VerifyRequest', 'VerifyResponse',
    'CriticRequest', 'CriticResponse',
    'FormatAcceptedRequest', 'FormatRejectedRequest', 'FormatResponse',
    'RenderRequest', 'RenderResponse',
    'SlotResult',
]

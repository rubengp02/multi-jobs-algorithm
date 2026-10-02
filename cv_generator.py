from __future__ import annotations

import base64
import os
import re
from pathlib import Path

from models import JobItem

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
PHOTO_PATH = ASSETS_DIR / "profile_photo.png"


def _get_photo_b64() -> str:
    if PHOTO_PATH.exists():
        return base64.b64encode(PHOTO_PATH.read_bytes()).decode("utf-8")
    return ""


# Master Catalog of Ruben's Data (Spanish and English)
MASTER_DATA = {
    "es": {
        "name": "[TU_NOMBRE_COMPLETO]",
        "title": "Ingeniero Industrial especializado en Inteligencia Artificial y Machine Learning",
        "email": "tu_correo@ejemplo.com",
        "phone": "640 73 33 44",
        "location": "Valencia, España",
        "linkedin": "www.linkedin.com/in/tu-perfil",
        "linkedin_url": "https://www.linkedin.com/in/tu-perfil",
        "github": "github.com/rubengp02",
        "github_url": "https://github.com/rubengp02",
        "section_profile": "PERFIL PROFESIONAL",
        "profile_default": (
            "Ingeniero Industrial especializado en Inteligencia Artificial, con experiencia práctica desarrollando proyectos de "
            "Machine Learning, Deep Learning, visión artificial y aprendizaje por refuerzo profundo. Conocimientos sobre "
            "entrenamiento y evaluación de modelos, optimización de hiperparámetros y redes neuronales. Interesado en "
            "aplicaciones industriales de IA, automatización, mantenimiento predictivo, robótica y sistemas inteligentes."
        ),
        "section_experience": "EXPERIENCIA PROFESIONAL",
        "experience_items": [
            {
                "title": "Ingeniero, FIREFCO SL | Febrero-Julio 2025",
                "bullets": [
                    "Diseño y calculo de instalaciones de fontanería, saneamiento y PCI.",
                    "Supervisión y coordinación de personal y materiales.",
                ],
            },
            {"title": "Monitor, NI FU NI FA | Verano 2020-2025", "bullets": []},
            {
                "title": "Auxiliar de Servicios Generales | Septiembre 2024",
                "bullets": [],
            },
        ],
        "section_education": "FORMACIÓN ACADÉMICA",
        "education_items": [
            "Máster Inteligencia Artificial, Universidad Internacional de Valencia, 2025-2026",
            "Graduado Ingeniería de Tecnologías Industriales, Universidad Politécnica de Valencia, 2020-2025.",
            "Curso Programación Python, DataBoosters Academy, 2025.",
        ],
        "section_skills": "HABILIDADES DESTACADAS",
        "skills_left": [
            ("Python", "Pandas, Numpy, Matplotlib, Seaborn, SQL."),
            ("Machine Learning", "Scikit-Learn, XGBoost, H2O AutoML, TPOT, Optuna."),
            ("Deep Learning", "TensorFlow, Keras, PyTorch, CNN, LLMs, RAG."),
        ],
        "skills_right": [
            ("Reinforcement Learning", "Gym, Atari, DQN, Q-Learning, Dueling DQN."),
            ("Visión Artificial", "OpenCV, OCR, Detección en Tiempo Real."),
            ("Otros", "Git, Docker, FastAPI, PostgreSQL, Linux, N8n, Claude Code."),
        ],
        "section_projects": "PROYECTOS",
        "projects": {
            "predictive_maintenance": {
                "title": "AutoML multiobjetivo para mantenimiento predictivo",
                "tags": "scikit-learn · LightGBM · XGBoost · H2O AutoML · Optuna · NSGA-II · TPOT",
                "desc_type": "p",
                "text": "Desarrollo de un pipeline experimental para predecir la vida útil restante de motores turbofan utilizando NASA C-MAPSS.",
            },
            "atari_rl": {
                "title": "Aprendizaje por refuerzo profundo para videojuegos Atari",
                "tags": "Python · TensorFlow/Keras · Keras-RL · Gym · DQN · Double DQN · Dueling DQN",
                "desc_type": "ul",
                "bullets": [
                    "Desarrollo y entrenamiento de agentes de aprendizaje por refuerzo profundo para el entorno Space Invaders.",
                    "Diseño de una red neuronal convolucional para aprender directamente a partir de imágenes del entorno.",
                ],
            },
            "vision_bot": {
                "title": "Bot autónomo basado en visión artificial",
                "tags": "OpenCV · OCR",
                "desc_type": "ul",
                "bullets": [
                    "Sistema automatizado capaz de detectar eventos en pantalla mediante visión artificial.",
                    "Implementación de lógica de decisión automática y uso de OCR.",
                ],
            },
            "cnn_classifier": {
                "title": "Clasificador de imágenes con CNN y redes neuronales",
                "tags": "TensorFlow · Keras · CNN · Preprocesamiento de datos · Aumento de datos",
                "desc_type": "ul",
                "bullets": [
                    "Diseño y entrenamiento de una red neuronal convolucional para clasificación de imágenes.",
                    "Evaluación del modelo sobre datos no vistos.",
                ],
            },
            "ajudes_clares": {
                "title": "AjudesClares: asistente RAG bilingüe para ayudas públicas",
                "tags": "Python · NLP · RAG · BM25F · Embeddings · FAISS · LLM · FastAPI · Streamlit · Docker",
                "desc_type": "ul",
                "bullets": [
                    "Asistente en castellano y valenciano para consultar becas, vivienda y empleo juvenil mediante fuentes oficiales.",
                    "Pipeline RAG con recuperación híbrida, reranking, respuestas con evidencias, evaluación del ranking, API REST e interfaz web.",
                ],
            },
            "recovery_intelligence": {
                "title": "Recovery Intelligence: Plataforma de IA para seguimiento en rehabilitación",
                "tags": "React/TS · FastAPI · PostgreSQL · OpenAI",
                "desc_type": "p",
                "text": "Priorización determinista/explicable, gpt-4.1-mini para tareas lingüísticas, human-in-the-loop, grounding, Structured Outputs, 120 evals deterministas, validación externa controlada, CI/E2E y deployment público.",
            },
        },
        "section_additional": "INFORMACIÓN ADICIONAL",
        "languages_label": "Idiomas",
        "languages": ["Español: Nativo", "Valenciano: Nativo", "Inglés: Avanzado"],
        "license_label": "Permiso de conducción B",
    },
    "en": {
        "name": "[TU_NOMBRE_COMPLETO]",
        "title": "Industrial Engineer specialized in Artificial Intelligence and Machine Learning",
        "email": "tu_correo@ejemplo.com",
        "phone": "640 73 33 44",
        "location": "Valencia, Spain",
        "linkedin": "www.linkedin.com/in/tu-perfil",
        "linkedin_url": "https://www.linkedin.com/in/tu-perfil",
        "github": "github.com/rubengp02",
        "github_url": "https://github.com/rubengp02",
        "section_profile": "PROFESSIONAL PROFILE",
        "profile_default": (
            "Industrial Engineer specialized in Artificial Intelligence with hands-on experience developing projects in "
            "Machine Learning, Deep Learning, Computer Vision, and Deep Reinforcement Learning. Knowledgeable in "
            "model training and evaluation, hyperparameter optimization, and neural networks. Interested in industrial AI "
            "applications, automation, predictive maintenance, robotics, and intelligent systems."
        ),
        "section_experience": "PROFESIONAL EXPERIENCE",
        "experience_items": [
            {
                "title": "Engineer, FIREFCO SL | February -July 2025",
                "bullets": [
                    "Design and calculation of plumbing, drainage, and fire protection system installations.",
                    "Supervision and coordination of personnel and materials.",
                ],
            },
            {"title": "Camp Counselor, NI FU NI FA | Summer 2020-2025", "bullets": []},
            {"title": "General Services Assistant | Septiembre 2024", "bullets": []},
        ],
        "section_education": "EDUCATION",
        "education_items": [
            "Master’s Degree in Artificial Intelligence, Universidad Internacional de Valencia, 2025-2026",
            "Bachelor’s Degree in Industrial Technologies Engineering, Universidad Politécnica de Valencia, 2020-2025.",
            "Python Programming Course, DataBoosters Academy, 2025.",
        ],
        "section_skills": "TECHNICAL SKILLS",
        "skills_left": [
            ("Python", "Pandas, Numpy, Matplotlib, Seaborn, SQL."),
            ("Machine Learning", "Scikit-Learn, XGBoost, H2O AutoML, TPOT, Optuna."),
            ("Deep Learning", "TensorFlow, Keras, PyTorch, CNN, LLMs, RAG."),
        ],
        "skills_right": [
            ("Reinforcement Learning", "Gym, Atari, DQN, Q-Learning, Dueling DQN."),
            ("Visión Artificial", "OpenCV, OCR, Real-time Computer Vision."),
            ("Otros", "Git, Docker, FastAPI, PostgreSQL, Linux, N8n, Claude Code."),
        ],
        "section_projects": "PROJECTS",
        "projects": {
            "predictive_maintenance": {
                "title": "Multi-objective AutoML for Predictive Maintenance",
                "tags": "scikit-learn · LightGBM · XGBoost · H2O AutoML · Optuna · NSGA-II · TPOT",
                "desc_type": "p",
                "text": "Development of an experimental pipeline to predict the Remaining Useful Life (RUL) of turbofan engines using the NASA C-MAPSS dataset.",
            },
            "atari_rl": {
                "title": "Deep Reinforcement Learning for Atari Games",
                "tags": "Python · TensorFlow/Keras · Keras-RL · Gym · DQN · Double DQN · Dueling DQN",
                "desc_type": "ul",
                "bullets": [
                    "Development and training of deep reinforcement learning agents for the Space Invaders environment.",
                    "Design of a convolutional neural network to learn directly from game screen images.",
                ],
            },
            "vision_bot": {
                "title": "Autonomous Bot Based on Computer Vision",
                "tags": "OpenCV · OCR",
                "desc_type": "ul",
                "bullets": [
                    "Automated system capable of detecting on-screen events using computer vision.",
                    "Implementation of automated decision-making logic and OCR.",
                ],
            },
            "cnn_classifier": {
                "title": "Image Classifier with CNN and Neural Networks",
                "tags": "TensorFlow · Keras · CNN · Data Preprocessing · Data Augmentation",
                "desc_type": "ul",
                "bullets": [
                    "Design and training of a convolutional neural network for image classification.",
                    "Model evaluation on previously unseen data.",
                ],
            },
            "ajudes_clares": {
                "title": "AjudesClares: Bilingual RAG Assistant for Public Grants",
                "tags": "Python · NLP · RAG · BM25F · Embeddings · FAISS · LLM · FastAPI · Streamlit · Docker",
                "desc_type": "ul",
                "bullets": [
                    "Bilingual Spanish–Valencian assistant for retrieving information on scholarships, housing support, and youth employment programmes from official sources.",
                    "End-to-end RAG pipeline featuring hybrid retrieval, reranking, evidence-grounded responses, ranking evaluation, a REST API, and a web interface.",
                ],
            },
            "recovery_intelligence": {
                "title": "Recovery Intelligence: AI Platform for Rehabilitation Follow-up",
                "tags": "React/TS · FastAPI · PostgreSQL · OpenAI",
                "desc_type": "p",
                "text": "Deterministic and explainable prioritization, GPT-4.1 mini for language tasks, human-in-the-loop workflows, grounding, Structured Outputs, 120 deterministic evaluations, controlled external validation, CI/E2E testing, and public deployment.",
            },
        },
        "section_additional": "ADDITIONAL INFORMATION",
        "languages_label": "Languages",
        "languages": ["Spanish: Native", "Valencian: Native", "English: Professional"],
        "license_label": "Driving Licence: Category B",
    },
}


def _detect_language(job: JobItem | None = None, description: str = "") -> str:
    text = f"{job.title if job else ''} {description}".lower()
    english_cues = [
        "we are looking",
        "requirements",
        "responsibilities",
        "skills",
        "experience with",
        "role",
        "bachelor",
        "master",
        "team",
    ]
    spanish_cues = [
        "requisitos",
        "experiencia",
        "buscamos",
        "funciones",
        "ofrecemos",
        "grado",
        "ingeniero",
        "jornada",
    ]
    en_score = sum(1 for c in english_cues if c in text)
    es_score = sum(1 for c in spanish_cues if c in text)
    return "en" if en_score > es_score + 1 else "es"


def _reorder_projects_and_skills(job: JobItem | None, description: str, lang: str):
    """
    Dynamically prioritizes projects and technical skills to match the job offer ATS profile.
    """
    text = f"{job.title if job else ''} {description}".lower()
    data = MASTER_DATA[lang]
    all_projects = data["projects"]

    # Priority keys determination
    if any(
        k in text
        for k in [
            "vision",
            "opencv",
            "yolo",
            "cnn",
            "image",
            "imagen",
            "video",
            "tracking",
        ]
    ):
        order = [
            "vision_bot",
            "cnn_classifier",
            "atari_rl",
            "ajudes_clares",
            "recovery_intelligence",
            "predictive_maintenance",
        ]
        custom_skills_right = [
            ("Visión Artificial", "OpenCV, OCR, YOLO, CNNs, Video Tracking."),
            ("Deep Learning", "PyTorch, TensorFlow, Keras, CNNs."),
            ("Otros", "Git, Docker, Linux, CI/CD, Pydantic."),
        ]
    elif any(
        k in text
        for k in [
            "rag",
            "llm",
            "nlp",
            "fastapi",
            "docker",
            "faiss",
            "langchain",
            "agent",
            "backend",
        ]
    ):
        order = [
            "ajudes_clares",
            "recovery_intelligence",
            "predictive_maintenance",
            "vision_bot",
            "cnn_classifier",
            "atari_rl",
        ]
        custom_skills_right = [
            ("GenAI & RAG", "FAISS, BM25F, OpenAI API, LangChain, Embeddings."),
            (
                "Backend & Cloud",
                "FastAPI, PostgreSQL, Docker, REST APIs, Microservicios.",
            ),
            ("Otros", "Git, CI/CD, Pydantic, TypeScript, Linux."),
        ]
    elif any(
        k in text
        for k in [
            "mantenimiento",
            "predictiv",
            "automl",
            "xgboost",
            "industrial",
            "turbofan",
            "plc",
            "scada",
            "iot",
        ]
    ):
        order = [
            "predictive_maintenance",
            "ajudes_clares",
            "recovery_intelligence",
            "vision_bot",
            "cnn_classifier",
            "atari_rl",
        ]
        custom_skills_right = [
            ("AutoML & Predictivo", "XGBoost, LightGBM, Optuna, H2O AutoML, NSGA-II."),
            ("Ingeniería & Automat.", "PLC, SCADA, Instalaciones, PCI, Normativas."),
            ("Otros", "Git, N8n, Python Industrial, Docker."),
        ]
    elif any(k in text for k in ["reinforcement", "rl", "gym", "game", "robot"]):
        order = [
            "atari_rl",
            "vision_bot",
            "predictive_maintenance",
            "cnn_classifier",
            "ajudes_clares",
            "recovery_intelligence",
        ]
        custom_skills_right = data["skills_right"]
    else:
        order = [
            "predictive_maintenance",
            "atari_rl",
            "vision_bot",
            "cnn_classifier",
            "ajudes_clares",
            "recovery_intelligence",
        ]
        custom_skills_right = data["skills_right"]

    ordered_projects = [all_projects[k] for k in order if k in all_projects]
    return ordered_projects, custom_skills_right


def generate_cv_html(job: JobItem | None = None, description: str = "") -> str:
    """
    Renders an exact, pixel-perfect HTML replica of the candidate's CV with ATS keyword adaptation.
    Preserves original typography, line-heights, and visual proportions while utilizing all rich data.
    """
    lang = _detect_language(job, description)
    data = MASTER_DATA[lang]
    photo_b64 = _get_photo_b64()

    projects, skills_right = _reorder_projects_and_skills(job, description, lang)
    skills_left = data["skills_left"]

    # 1. Generate Projects HTML
    proj_html_blocks = []
    for p in projects:
        if p["desc_type"] == "p":
            desc_part = f'<p class="desc-text">{p["text"]}</p>'
        else:
            bullets = "".join([f"<li>{b}</li>" for b in p["bullets"]])
            desc_part = f'<ul class="clean-bullets">{bullets}</ul>'

        block = f"""
        <div class="project-item">
          <div class="project-title">{p["title"]}</div>
          <div class="project-tags">{p["tags"]}</div>
          {desc_part}
        </div>
        """
        proj_html_blocks.append(block)
    projects_html = "\n".join(proj_html_blocks)

    # 2. Generate Experience HTML
    exp_left = data["experience_items"][0]
    exp_left_bullets = "".join([f"<li>{b}</li>" for b in exp_left["bullets"]])
    exp_right_1 = data["experience_items"][1]["title"]
    exp_right_2 = data["experience_items"][2]["title"]

    # 3. Generate Skills HTML
    s_left_html = "".join(
        [f"<li><strong>{name}:</strong> {val}</li>" for name, val in skills_left]
    )
    s_right_html = "".join(
        [f"<li><strong>{name}:</strong> {val}</li>" for name, val in skills_right]
    )

    # 4. Generate Education HTML
    edu_html = "".join(
        [
            f'<div class="bold-title" style="margin-bottom: 2px;">{e}</div>'
            for e in data["education_items"]
        ]
    )

    # 5. Generate Languages HTML
    lang_html = "".join([f"<li>{l}</li>" for l in data["languages"]])

    html = f'''<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<style>
  @page {{
    size: A4 portrait;
    margin: 8mm 12mm 8mm 12mm;
  }}
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}
  body {{
    font-family: Arial, "Helvetica Neue", Helvetica, sans-serif;
    color: #1a1a1a;
    font-size: 8.2pt;
    line-height: 1.27;
    background: #ffffff;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  .header {{
    display: flex;
    align-items: center;
    margin-bottom: 5px;
  }}
  .photo-container {{
    width: 80px;
    height: 100px;
    flex-shrink: 0;
    margin-right: 14px;
  }}
  .photo-container img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: 2px;
  }}
  .header-info {{
    flex: 1;
  }}
  .header-name {{
    font-size: 20pt;
    font-weight: 800;
    letter-spacing: 0.4px;
    color: #000000;
    margin-bottom: 2px;
  }}
  .header-title {{
    font-size: 10.5pt;
    font-weight: 400;
    color: #2b2b2b;
    margin-bottom: 4px;
    line-height: 1.2;
  }}
  .contact-row {{
    font-size: 8pt;
    color: #222222;
    margin-bottom: 1.5px;
  }}
  .contact-link {{
    color: #1a1a1a;
    text-decoration: underline;
  }}
  .section-banner {{
    background-color: #111111;
    color: #ffffff;
    font-size: 9.5pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    padding: 2.2px 6px;
    margin-top: 5.5px;
    margin-bottom: 3.5px;
    border-radius: 1px;
  }}
  .grid-2col {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    column-gap: 16px;
  }}
  .bold-title {{
    font-weight: 700;
    font-size: 8.4pt;
    color: #000000;
  }}
  .project-item {{
    margin-bottom: 3.5px;
  }}
  .project-title {{
    font-weight: 700;
    font-size: 8.5pt;
    color: #000000;
  }}
  .project-tags {{
    color: #0066cc;
    font-size: 7.6pt;
    font-weight: 600;
    margin: 0.5px 0 1.5px 0;
  }}
  ul.clean-bullets {{
    margin-left: 14px;
    list-style-type: disc;
  }}
  ul.clean-bullets li {{
    margin-bottom: 1px;
    font-size: 8pt;
  }}
  p.desc-text {{
    font-size: 8pt;
    color: #1f1f1f;
    line-height: 1.26;
  }}
</style>
</head>
<body>

<div class="header">
  <div class="photo-container">
    <img src="data:image/png;base64,{photo_b64}" alt="[TU_NOMBRE_COMPLETO]" />
  </div>
  <div class="header-info">
    <div class="header-name">{data["name"]}</div>
    <div class="header-title">{data["title"]}</div>
    <div class="contact-row">{"Correo" if lang == "es" else "Mail"}: <span class="contact-link">{data["email"]}</span></div>
    <div class="contact-row">{"Teléfono" if lang == "es" else "Phone"}: <span class="contact-link">{data["phone"]}</span> &nbsp;&nbsp;&nbsp;&nbsp; {data["location"]}</div>
    <div class="contact-row">LinkedIn: <a href="{data["linkedin_url"]}" class="contact-link">{data["linkedin"]}</a> &nbsp;&nbsp;&nbsp;&nbsp; GitHub: <a href="{data["github_url"]}" class="contact-link">{data["github"]}</a></div>
  </div>
</div>

<div class="section-banner">{data["section_profile"]}</div>
<p class="desc-text">
  {data["profile_default"]}
</p>

<div class="section-banner">{data["section_experience"]}</div>
<div class="grid-2col">
  <div>
    <div class="bold-title">{exp_left["title"]}</div>
    <ul class="clean-bullets">
      {exp_left_bullets}
    </ul>
  </div>
  <div>
    <div class="bold-title">{exp_right_1}</div>
    <div class="bold-title" style="margin-top: 3px;">{exp_right_2}</div>
  </div>
</div>

<div class="section-banner">{data["section_education"]}</div>
{edu_html}

<div class="section-banner">{data["section_skills"]}</div>
<div class="grid-2col">
  <ul class="clean-bullets">
    {s_left_html}
  </ul>
  <ul class="clean-bullets">
    {s_right_html}
  </ul>
</div>

<div class="section-banner">{data["section_projects"]}</div>
{projects_html}

<div class="section-banner">{data["section_additional"]}</div>
<div class="grid-2col">
  <div>
    <div class="bold-title">{data["languages_label"]}</div>
    <ul class="clean-bullets">
      {lang_html}
    </ul>
  </div>
  <div>
    <div class="bold-title">{data["license_label"]}</div>
  </div>
</div>

</body>
</html>'''
    return html


def generate_cv_pdf(
    job: JobItem | None = None, description: str = "", output_path: str | None = None
) -> str:
    """
    Compiles the tailored CV HTML into a crisp, vector-based PDF file using Playwright.
    Returns the absolute path to the generated PDF.
    """
    from playwright.sync_api import sync_playwright

    html_content = generate_cv_html(job, description)

    if output_path is None:
        safe_comp = re.sub(r"[^a-zA-Z0-9_-]", "_", job.company) if job else "General"
        os.makedirs(str(BASE_DIR / "data" / "cvs"), exist_ok=True)
        out_file = BASE_DIR / "data" / "cvs" / f"CV_Generado_{safe_comp}.pdf"
    else:
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page()
        page.set_content(html_content)
        page.pdf(
            path=str(out_file),
            format="A4",
            print_background=True,
            margin={"top": "8mm", "bottom": "8mm", "left": "12mm", "right": "12mm"},
        )
        browser.close()

    return str(out_file)

from matcher import calculate_match_score, extract_job_features
from models import JobItem
from relevance import decision_from_dict, evaluate_relevance


def format_job_message(
    job: JobItem, description: str = "", cycle_num: int | None = None
) -> str:
    description = description or job.description
    (
        _legacy_score,
        _tags,
        stack,
        salary,
        experience,
        modality,
        company_type,
        freshness,
    ) = calculate_match_score(
        job.title,
        description,
        job.location,
        job.company,
        getattr(job, "posted_within_1h", False),
    )
    features = job.features or extract_job_features(
        job.title, description, job.location
    )
    decision = decision_from_dict(features.get("relevance"))
    if decision is None:
        decision = evaluate_relevance(job, description)
    score = decision.score
    experience_details = features.get("experience", {})
    if isinstance(experience_details, dict):
        experience = str(experience_details.get("display") or experience)
    stack = list(features.get("stack") or stack)
    salary = str(features.get("salary") or salary)
    modality = str(features.get("modality") or modality)

    if score >= 90:
        score_badge = f"🌟 *TOP MATCH: {score}%*"
    elif score >= 80:
        score_badge = f"🔥 *Match: {score}%*"
    else:
        score_badge = f"⚡ *Match: {score}%*"

    if modality == "100% Remoto":
        mod_badge = "🏠 *Modalidad:* 100% Remoto"
    elif modality == "Híbrido":
        mod_badge = "🏢 *Modalidad:* Híbrido"
    elif modality == "Presencial":
        mod_badge = "📍 *Modalidad:* Presencial"
    else:
        mod_badge = f"📍 *Modalidad:* {modality}"

    header_title = (
        f"🆕 *OFERTA #{cycle_num}* [{job.source.upper()}] — {score_badge}"
        if cycle_num
        else f"🆕 *NUEVA OFERTA* [{job.source.upper()}] — {score_badge}"
    )

    blocks: list[str] = [
        header_title,
        f"💼 *Puesto:* {job.title}\n🏢 *Empresa:* {job.company} ({company_type})",
        f"📍 *Ubicación:* {job.location}\n{mod_badge}\n🎓 *Experiencia:* {experience}\n⏱️ *Estado:* {freshness}",
    ]
    if decision.status == "warning":
        evidence = ", ".join(
            item.split(":", 1)[-1] for item in decision.positive_evidence[:3]
        )
        reason = f" Evidencia: {evidence}." if evidence else ""
        blocks.append(f"⚠️ *Relevancia a revisar* ({decision.family}).{reason}")

    block3_lines: list[str] = []
    if salary:
        block3_lines.append(f"💰 *Salario:* {salary}")
    if stack:
        block3_lines.append(f"🛠️ *Stack:* {', '.join(stack)}")
    architecture = features.get("architecture", [])
    if isinstance(architecture, list) and architecture:
        block3_lines.append(
            f"🏗️ *Arquitectura:* {', '.join(str(value) for value in architecture)}"
        )
    if block3_lines:
        blocks.append("\n".join(block3_lines))

    feature_lines: list[str] = []
    feature_labels = (
        ("contract_types", "📄 *Contrato*"),
        ("work_schedules", "🕒 *Jornada*"),
        ("education", "🎓 *Formación*"),
        ("languages", "🗣️ *Idiomas*"),
        ("certifications", "🏅 *Certificaciones*"),
        ("benefits", "🎁 *Beneficios*"),
    )
    for key, label in feature_labels:
        values = features.get(key, [])
        if isinstance(values, list) and values:
            feature_lines.append(
                f"{label}: {', '.join(str(value) for value in values)}"
            )
    if feature_lines:
        blocks.append("\n".join(feature_lines))

    target_qa_num = cycle_num if cycle_num else 1
    footer_lines = [f"🔗 *Enlace:* {job.url}"]
    footer_lines.append(
        f"⚡ *Acciones rápidas:* Usa */cv {target_qa_num}* (CV PDF a medida), */qa {target_qa_num}* o */tailor {target_qa_num}*."
    )
    blocks.append("\n".join(footer_lines))

    return "\n\n".join(blocks)

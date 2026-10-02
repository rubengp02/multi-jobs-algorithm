import unittest

from matcher import extract_experience_details, extract_job_features


class JobFeatureExtractionTests(unittest.TestCase):
    def test_extracts_required_experience_and_all_public_requirements(self) -> None:
        text = (
            "Requisito imprescindible: experiencia minima de 3 anos con Python, Docker y PostgreSQL. "
            "Nivel de ingles C1. Contrato indefinido, jornada completa y horario flexible, modalidad hibrida. "
            "Grado en Ingenieria Informatica. AWS Certified y Scrum Master. "
            "Seguro medico, ticket restaurant y retribucion flexible."
        )

        features = extract_job_features("Backend engineer", text, "Valencia")
        experience = features["experience"]

        self.assertEqual(experience["minimum_years"], 3)
        self.assertIsNone(experience["maximum_years"])
        self.assertEqual(experience["level"], "Mid")
        self.assertEqual(experience["requirement"], "Requerida")
        self.assertIn("Python", experience["skills"])
        self.assertIn("Docker", experience["skills"])
        self.assertIn("PostgreSQL", experience["skills"])
        self.assertIn("Indefinido", features["contract_types"])
        self.assertIn("Jornada completa", features["work_schedules"])
        self.assertIn("Horario flexible", features["work_schedules"])
        self.assertIn("Ingles", features["languages"])
        self.assertIn("AWS Certification", features["certifications"])
        self.assertIn("Scrum", features["certifications"])
        self.assertIn("Seguro medico", features["benefits"])

    def test_separates_architecture_from_stack(self) -> None:
        features = extract_job_features(
            "Desarrollador Go", "Microservicios y API REST."
        )

        self.assertNotIn("Microservices", features["stack"])
        self.assertIn("Microservicios", features["architecture"])
        self.assertIn("API REST", features["architecture"])

    def test_keeps_company_history_out_of_required_experience(self) -> None:
        details = extract_experience_details(
            "Empresa con 10 anos de experiencia en el sector. Oferta para perfiles junior."
        )

        self.assertIsNone(details["minimum_years"])
        self.assertEqual(details["level"], "Junior")

    def test_extracts_valued_experience_range_without_turning_it_into_required(
        self,
    ) -> None:
        details = extract_experience_details(
            "Se valorara entre 1 y 2 anos de experiencia en React y TypeScript."
        )

        self.assertEqual(details["minimum_years"], 1)
        self.assertEqual(details["maximum_years"], 2)
        self.assertEqual(details["requirement"], "Valorada")
        self.assertIn("React", details["skills"])
        self.assertIn("TypeScript", details["skills"])


if __name__ == "__main__":
    unittest.main()

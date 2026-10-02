import unittest

from matcher import extract_tech_stack


class ExtractTechStackTests(unittest.TestCase):
    def test_does_not_invent_a_stack_from_a_generic_role(self) -> None:
        self.assertEqual(
            extract_tech_stack("Software Engineer Junior para productos digitales"),
            [],
        )
        self.assertEqual(extract_tech_stack(""), [])

    def test_ai_family_does_not_imply_python_or_machine_learning(self) -> None:
        stack = extract_tech_stack("Buscamos Ingeniero de IA Generativa")

        self.assertEqual(stack, ["Artificial Intelligence", "Generative AI"])
        self.assertNotIn("Python", stack)
        self.assertNotIn("Machine Learning", stack)

    def test_detects_tools_missing_from_recent_job_history(self) -> None:
        stack = extract_tech_stack(
            "DevOps Engineer with Splunk for monitoring, observability and Grafana"
        )

        self.assertEqual(
            stack,
            ["DevOps", "Monitoring", "Observability", "Splunk", "Grafana"],
        )

    def test_detects_non_profile_languages_and_platforms(self) -> None:
        stack = extract_tech_stack(
            "Scala Developer with Oracle Database, SQL Server and Kubernetes"
        )

        self.assertEqual(
            stack,
            ["Scala", "SQL", "Oracle", "Microsoft SQL Server", "Kubernetes"],
        )
        self.assertEqual(
            extract_tech_stack("Desarrollador GO para microservicios"),
            ["Go"],
        )

    def test_detects_named_platforms_found_in_recent_titles(self) -> None:
        self.assertEqual(
            extract_tech_stack("Backend Developer Java - Camunda / 100% Teletrabajo"),
            ["Java", "Camunda"],
        )
        self.assertEqual(
            extract_tech_stack("Desarrollador/a Apis con Apigee"),
            ["Apigee"],
        )
        self.assertEqual(
            extract_tech_stack("Embedded IoT Engineer"),
            ["IoT"],
        )
        self.assertEqual(extract_tech_stack("iOS Engineer - Platform"), ["iOS"])

    def test_detects_explicit_tools_found_in_the_linkedin_audit(self) -> None:
        stack = extract_tech_stack(
            "Python, MATLAB y R. Power Apps, SharePoint y Excel. "
            "React con Redux, OpenAPI, SQLAlchemy, Alembic, Jest y servicios Dockerizados."
        )

        self.assertEqual(
            stack,
            [
                "Python",
                "R",
                "React",
                "OpenAPI",
                "Redux",
                "SQLAlchemy",
                "Alembic",
                "Power Apps",
                "SharePoint",
                "Excel",
                "Docker",
                "MATLAB",
                "Jest",
            ],
        )


if __name__ == "__main__":
    unittest.main()

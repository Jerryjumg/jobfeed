"""Checks for the matching and sectioning edge cases jdfit has to get right.

Run with:  python -m unittest -v
"""
import unittest

import jdfit

TAXONOMY = jdfit.load_json(jdfit.HERE / "taxonomy.json")
PATTERNS = jdfit.compile_taxonomy(TAXONOMY)
PROFILE = {"have": ["Swift", "Python", "SQL"], "learning": ["Power BI"],
           "max_years_required": 2, "red_flags": ["security clearance"]}


def skills(text):
    return jdfit.find_skills(text, PATTERNS)


class MatchingTests(unittest.TestCase):
    def test_java_does_not_match_inside_javascript(self):
        self.assertNotIn("Java", skills("Strong JavaScript skills"))
        self.assertIn("JavaScript", skills("Strong JavaScript skills"))

    def test_symbols_in_names(self):
        self.assertIn("C#", skills("Experience with C# and .NET"))
        self.assertIn("ASP.NET / .NET", skills("Experience with C# and .NET"))
        self.assertIn("C++", skills("C++ or Rust"))
        self.assertIn("Node.js", skills("Node.js services"))

    def test_git_does_not_match_inside_github(self):
        self.assertEqual({"GitHub"}, skills("We use GitHub") & {"Git", "GitHub"})

    def test_common_words_are_not_skills(self):
        self.assertNotIn("REST APIs", skills("You will work with the rest of the team"))
        self.assertNotIn("React", skills("Analysts react quickly to incidents"))
        self.assertNotIn("Excel", skills("You excel in ambiguity"))
        self.assertNotIn("Excel", skills("Excel at written communication"))

    def test_react_native_is_not_also_react(self):
        self.assertIn("React Native", skills("React Native experience"))
        self.assertNotIn("React", skills("React Native experience"))

    def test_case_sensitive_capitalised_alias(self):
        self.assertIn("Swift", skills("Strong Swift skills"))
        self.assertNotIn("Swift", skills("swift turnaround on tickets"))
        self.assertIn("MES", skills("manufacturing execution system rollout"))


class SectionTests(unittest.TestCase):
    def test_preferred_heading_beats_qualification_keyword(self):
        self.assertEqual("preferred", jdfit.classify_heading("Preferred Qualifications"))
        self.assertEqual("required", jdfit.classify_heading("Minimum Qualifications:"))

    def test_bullets_and_sentences_are_not_headings(self):
        self.assertIsNone(jdfit.classify_heading("- Experience with Python"))
        self.assertIsNone(jdfit.classify_heading("3+ years of experience"))
        self.assertIsNone(jdfit.classify_heading("Experience with Python and SQL"))

    def test_inline_plus_moves_line_to_preferred(self):
        tagged, found = jdfit.split_sections("Requirements\n- Python\n- Kubernetes is a plus\n")
        self.assertTrue(found)
        self.assertEqual([("required", "- Python"), ("preferred", "- Kubernetes is a plus")], tagged)

    def test_benefits_are_ignored(self):
        tagged, _ = jdfit.split_sections("Requirements\n- Python\nBenefits\n- AWS credits\n")
        self.assertEqual([("required", "- Python")], tagged)


class AssessmentTests(unittest.TestCase):
    def test_years_gate(self):
        jd = "Requirements\n- 5+ years of experience with Python\n"
        self.assertEqual("Too senior", jdfit.assess(jd, PROFILE, PATTERNS).verdict)

    def test_years_in_preferred_do_not_gate(self):
        jd = "Requirements\n- Python\nPreferred\n- 5+ years of experience with SQL\n"
        report = jdfit.assess(jd, PROFILE, PATTERNS)
        self.assertIsNone(report.years_required)

    def test_red_flag_wins(self):
        jd = "Requirements\n- Python\n- Active security clearance\n"
        self.assertEqual("Skip (red flag)", jdfit.assess(jd, PROFILE, PATTERNS).verdict)

    def test_learning_is_never_counted_as_a_match(self):
        jd = "Requirements\n- Power BI\n"
        report = jdfit.assess(jd, PROFILE, PATTERNS)
        self.assertEqual(0.0, report.score)
        self.assertEqual("learning", report.skills[0].status)

    def test_resume_gap_detection(self):
        jd = "Requirements\n- Python and SQL\n"
        report = jdfit.assess(jd, PROFILE, PATTERNS, resume_text="Python developer")
        missing = [h.skill for h in report.skills if h.on_resume is False]
        self.assertEqual(["SQL"], missing)

    def test_required_outweighs_preferred(self):
        jd = "Requirements\n- Python\nNice to have\n- Terraform\n"
        self.assertEqual(0.75, jdfit.assess(jd, PROFILE, PATTERNS).score)


if __name__ == "__main__":
    unittest.main()

"""speech.py: what the voice is given, and what the writer must rewrite."""
import unittest

from postcrew import speech


class SpeakableTests(unittest.TestCase):
    def test_complexity_maths_and_money(self):
        self.assertEqual(speech.speakable("O(n) beats O(n^2)."), "O of n beats O of n squared.")
        self.assertEqual(speech.speakable("Then 9 - 7 = 2."), "Then nine minus seven equals two.")
        self.assertEqual(speech.speakable("It costs $4.50, or 1,000 times that."), "It costs four dollars and fifty cents, or one thousand times that.")
        self.assertEqual(speech.speakable("A 95% hit rate and 20ms latency."), "A ninety five percent hit rate and twenty milliseconds latency.")

    def test_years_versions_ranges_and_times(self):
        self.assertEqual(speech.speakable("Since 2026 we use v2.1."), "Since twenty twenty six we use version two point one.")
        self.assertEqual(speech.speakable("Read pages 1-3."), "Read pages one to three.")
        self.assertEqual(speech.speakable("At 9:30 AM."), "At nine thirty A M.")

    def test_acronyms_and_tool_names_are_said_the_way_people_say_them(self):
        out = speech.speakable("kubectl, nginx, SQL, JSON, OAuth2 and the API over HTTPS")
        self.assertEqual(out, "cube control, engine X, sequel, jason, oh auth two and the A P I over H T T P S")
        self.assertEqual(speech.speakable("The LOAD is NOT high."), "The load is not high.")
        self.assertEqual(speech.speakable("An XYZ thing."), "An X Y Z thing.")

    def test_code_names_and_addresses_become_words(self):
        self.assertEqual(speech.speakable("two_sum and twoSum"), "two sum and two Sum")
        self.assertEqual(speech.speakable("see example.com/docs"), "see example dot com docs")
        self.assertEqual(speech.speakable("C++ or C#"), "C plus plus or C sharp")

    def test_no_symbol_is_left_in_what_the_voice_gets(self):
        out = speech.speakable("x -> y, a != b, n * m, seen[i] = 3 + 4; 100% → \U0001F600")
        for ch in "->!=*[]+%→\U0001F600":
            self.assertNotIn(ch, out)


class ProblemTests(unittest.TestCase):
    def test_plain_teaching_text_has_no_problems(self):
        self.assertEqual(speech.problems("One pass gives O of n time. Take A, B, C. The window is three long, a good fit."), [])

    def test_code_addresses_and_lone_letters_are_flagged(self):
        self.assertTrue(speech.problems("Call two_sum on nums[i] == 3."))
        self.assertTrue(speech.problems("Go to example.com now."))
        self.assertTrue(speech.problems("Right moves over a, b, c."))
        self.assertTrue(speech.problems("Remove the old a and go on."))

    def test_an_ellipsis_in_the_middle_of_a_phrase_is_flagged(self):
        self.assertTrue(any("ellipsis" in p for p in speech.problems("Brackets close... last opened, first closed.")))
        self.assertEqual(speech.problems("A hash is a fingerprint... It never changes."), [])
        self.assertEqual(speech.problems("What did we learn... Use a stack."), [])

    def test_words_the_voice_cannot_say_are_flagged(self):
        self.assertTrue(any("vowels" in p for p in speech.problems("Use the grmbl tool.")))
        self.assertTrue(any("letters and digits" in p for p in speech.problems("Open the x7b2 port.")))
        self.assertEqual(speech.problems("Use kubectl with nginx."), [])   # known tools are respelled, not flagged


if __name__ == "__main__":
    unittest.main()

import copy
import hashlib
import os
import shutil
from datetime import timedelta
from zipfile import ZipFile

from django.conf import settings

from utils.api.tests import APITestCase

from .models import QuizTag, QuizIOMode
from .models import Quiz, QuizRuleType
from contest.models import Contest
from contest.tests import DEFAULT_CONTEST_DATA

from .views.admin import TestCaseAPI
from .utils import parse_quiz_template

DEFAULT_PROBLEM_DATA = {"_id": "A-110", "title": "test", "description": "<p>test</p>", "input_description": "test",
                        "output_description": "test", "time_limit": 1000, "memory_limit": 256, "difficulty": "Low",
                        "visible": True, "tags": ["test"], "languages": ["C", "C++", "Java", "Python2"], "template": {},
                        "samples": [{"input": "test", "output": "test"}], "spj": False, "spj_language": "C",
                        "spj_code": "", "spj_compile_ok": True, "test_case_id": "499b26290cc7994e0b497212e842ea85",
                        "test_case_score": [{"output_name": "1.out", "input_name": "1.in", "output_size": 0,
                                             "stripped_output_md5": "d41d8cd98f00b204e9800998ecf8427e",
                                             "input_size": 0, "score": 0}],
                        "io_mode": {"io_mode": QuizIOMode.standard, "input": "input.txt", "output": "output.txt"},
                        "share_submission": False,
                        "rule_type": "ACM", "hint": "<p>test</p>", "source": "test"}


class QuizCreateTestBase(APITestCase):
    @staticmethod
    def add_quiz(quiz_data, created_by):
        data = copy.deepcopy(quiz_data)
        if data["spj"]:
            if not data["spj_language"] or not data["spj_code"]:
                raise ValueError("Invalid spj")
            data["spj_version"] = hashlib.md5(
                (data["spj_language"] + ":" + data["spj_code"]).encode("utf-8")).hexdigest()
        else:
            data["spj_language"] = None
            data["spj_code"] = None
        if data["rule_type"] == QuizRuleType.OI:
            total_score = 0
            for item in data["test_case_score"]:
                if item["score"] <= 0:
                    raise ValueError("invalid score")
                else:
                    total_score += item["score"]
            data["total_score"] = total_score
        data["created_by"] = created_by
        tags = data.pop("tags")

        data["languages"] = list(data["languages"])

        quiz = Quiz.objects.create(**data)

        for item in tags:
            try:
                tag = QuizTag.objects.get(name=item)
            except QuizTag.DoesNotExist:
                tag = QuizTag.objects.create(name=item)
            quiz.tags.add(tag)
        return quiz


class QuizTagListAPITest(APITestCase):
    def test_get_tag_list(self):
        QuizTag.objects.create(name="name1")
        QuizTag.objects.create(name="name2")
        resp = self.client.get(self.reverse("quiz_tag_list_api"))
        self.assertSuccess(resp)


class TestCaseUploadAPITest(APITestCase):
    def setUp(self):
        self.api = TestCaseAPI()
        self.url = self.reverse("test_case_api")
        self.create_super_admin()

    def test_filter_file_name(self):
        self.assertEqual(self.api.filter_name_list(["1.in", "1.out", "2.in", ".DS_Store"], spj=False),
                         ["1.in", "1.out"])
        self.assertEqual(self.api.filter_name_list(["2.in", "2.out"], spj=False), [])

        self.assertEqual(self.api.filter_name_list(["1.in", "1.out", "2.in"], spj=True), ["1.in", "2.in"])
        self.assertEqual(self.api.filter_name_list(["2.in", "3.in"], spj=True), [])

    def make_test_case_zip(self):
        base_dir = os.path.join("/tmp", "test_case")
        shutil.rmtree(base_dir, ignore_errors=True)
        os.mkdir(base_dir)
        file_names = ["1.in", "1.out", "2.in", ".DS_Store"]
        for item in file_names:
            with open(os.path.join(base_dir, item), "w", encoding="utf-8") as f:
                f.write(item + "\n" + item + "\r\n" + "end")
        zip_file = os.path.join(base_dir, "test_case.zip")
        with ZipFile(os.path.join(base_dir, "test_case.zip"), "w") as f:
            for item in file_names:
                f.write(os.path.join(base_dir, item), item)
        return zip_file

    def test_upload_spj_test_case_zip(self):
        with open(self.make_test_case_zip(), "rb") as f:
            resp = self.client.post(self.url,
                                    data={"spj": "true", "file": f}, format="multipart")
            self.assertSuccess(resp)
            data = resp.data["data"]
            self.assertEqual(data["spj"], True)
            test_case_dir = os.path.join(settings.TEST_CASE_DIR, data["id"])
            self.assertTrue(os.path.exists(test_case_dir))
            for item in data["info"]:
                name = item["input_name"]
                with open(os.path.join(test_case_dir, name), "r", encoding="utf-8") as f:
                    self.assertEqual(f.read(), name + "\n" + name + "\n" + "end")

    def test_upload_test_case_zip(self):
        with open(self.make_test_case_zip(), "rb") as f:
            resp = self.client.post(self.url,
                                    data={"spj": "false", "file": f}, format="multipart")
            self.assertSuccess(resp)
            data = resp.data["data"]
            self.assertEqual(data["spj"], False)
            test_case_dir = os.path.join(settings.TEST_CASE_DIR, data["id"])
            self.assertTrue(os.path.exists(test_case_dir))
            for item in data["info"]:
                name = item["input_name"]
                with open(os.path.join(test_case_dir, name), "r", encoding="utf-8") as f:
                    self.assertEqual(f.read(), name + "\n" + name + "\n" + "end")


class QuizAdminAPITest(APITestCase):
    def setUp(self):
        self.url = self.reverse("quiz_admin_api")
        self.create_super_admin()
        self.data = copy.deepcopy(DEFAULT_PROBLEM_DATA)

    def test_create_quiz(self):
        resp = self.client.post(self.url, data=self.data)
        self.assertSuccess(resp)
        return resp

    def test_duplicate_display_id(self):
        self.test_create_quiz()

        resp = self.client.post(self.url, data=self.data)
        self.assertFailed(resp, "Display ID already exists")

    def test_spj(self):
        data = copy.deepcopy(self.data)
        data["spj"] = True

        resp = self.client.post(self.url, data)
        self.assertFailed(resp, "Invalid spj")

        data["spj_code"] = "test"
        resp = self.client.post(self.url, data=data)
        self.assertSuccess(resp)

    def test_get_quiz(self):
        self.test_create_quiz()
        resp = self.client.get(self.url)
        self.assertSuccess(resp)

    def test_get_one_quiz(self):
        quiz_id = self.test_create_quiz().data["data"]["id"]
        resp = self.client.get(self.url + "?id=" + str(quiz_id))
        self.assertSuccess(resp)

    def test_edit_quiz(self):
        quiz_id = self.test_create_quiz().data["data"]["id"]
        data = copy.deepcopy(self.data)
        data["id"] = quiz_id
        resp = self.client.put(self.url, data=data)
        self.assertSuccess(resp)


class QuizAPITest(QuizCreateTestBase):
    def setUp(self):
        self.url = self.reverse("quiz_api")
        admin = self.create_admin(login=False)
        self.quiz = self.add_quiz(DEFAULT_PROBLEM_DATA, admin)
        self.create_user("test", "test123")

    def test_get_quiz_list(self):
        resp = self.client.get(f"{self.url}?limit=10")
        self.assertSuccess(resp)

    def get_one_quiz(self):
        resp = self.client.get(self.url + "?id=" + self.quiz._id)
        self.assertSuccess(resp)


class ContestQuizAdminTest(APITestCase):
    def setUp(self):
        self.url = self.reverse("contest_quiz_admin_api")
        self.create_admin()
        self.contest = self.client.post(self.reverse("contest_admin_api"), data=DEFAULT_CONTEST_DATA).data["data"]

    def test_create_contest_quiz(self):
        data = copy.deepcopy(DEFAULT_PROBLEM_DATA)
        data["contest_id"] = self.contest["id"]
        resp = self.client.post(self.url, data=data)
        self.assertSuccess(resp)
        return resp.data["data"]

    def test_get_contest_quiz(self):
        self.test_create_contest_quiz()
        contest_id = self.contest["id"]
        resp = self.client.get(self.url + "?contest_id=" + str(contest_id))
        self.assertSuccess(resp)
        self.assertEqual(len(resp.data["data"]["results"]), 1)

    def test_get_one_contest_quiz(self):
        contest_quiz = self.test_create_contest_quiz()
        contest_id = self.contest["id"]
        quiz_id = contest_quiz["id"]
        resp = self.client.get(f"{self.url}?contest_id={contest_id}&id={quiz_id}")
        self.assertSuccess(resp)


class ContestQuizTest(QuizCreateTestBase):
    def setUp(self):
        admin = self.create_admin()
        url = self.reverse("contest_admin_api")
        contest_data = copy.deepcopy(DEFAULT_CONTEST_DATA)
        contest_data["password"] = ""
        contest_data["start_time"] = contest_data["start_time"] + timedelta(hours=1)
        self.contest = self.client.post(url, data=contest_data).data["data"]
        self.quiz = self.add_quiz(DEFAULT_PROBLEM_DATA, admin)
        self.quiz.contest_id = self.contest["id"]
        self.quiz.save()
        self.url = self.reverse("contest_quiz_api")

    def test_admin_get_contest_quiz_list(self):
        contest_id = self.contest["id"]
        resp = self.client.get(self.url + "?contest_id=" + str(contest_id))
        self.assertSuccess(resp)
        self.assertEqual(len(resp.data["data"]), 1)

    def test_admin_get_one_contest_quiz(self):
        contest_id = self.contest["id"]
        quiz_id = self.quiz._id
        resp = self.client.get("{}?contest_id={}&quiz_id={}".format(self.url, contest_id, quiz_id))
        self.assertSuccess(resp)

    def test_regular_user_get_not_started_contest_quiz(self):
        self.create_user("test", "test123")
        resp = self.client.get(self.url + "?contest_id=" + str(self.contest["id"]))
        self.assertDictEqual(resp.data, {"error": "error", "data": "Contest has not started yet."})

    def test_reguar_user_get_started_contest_quiz(self):
        self.create_user("test", "test123")
        contest = Contest.objects.first()
        contest.start_time = contest.start_time - timedelta(hours=1)
        contest.save()
        resp = self.client.get(self.url + "?contest_id=" + str(self.contest["id"]))
        self.assertSuccess(resp)


class AddQuizFromPublicQuizAPITest(QuizCreateTestBase):
    def setUp(self):
        admin = self.create_admin()
        url = self.reverse("contest_admin_api")
        contest_data = copy.deepcopy(DEFAULT_CONTEST_DATA)
        contest_data["password"] = ""
        contest_data["start_time"] = contest_data["start_time"] + timedelta(hours=1)
        self.contest = self.client.post(url, data=contest_data).data["data"]
        self.quiz = self.add_quiz(DEFAULT_PROBLEM_DATA, admin)
        self.url = self.reverse("add_contest_quiz_from_public_api")
        self.data = {
            "display_id": "1000",
            "contest_id": self.contest["id"],
            "quiz_id": self.quiz.id
        }

    def test_add_contest_quiz(self):
        resp = self.client.post(self.url, data=self.data)
        self.assertSuccess(resp)
        self.assertTrue(Quiz.objects.all().exists())
        self.assertTrue(Quiz.objects.filter(contest_id=self.contest["id"]).exists())


class ParseQuizTemplateTest(APITestCase):
    def test_parse(self):
        template_str = """
//PREPEND BEGIN
aaa
//PREPEND END

//TEMPLATE BEGIN
bbb
//TEMPLATE END

//APPEND BEGIN
ccc
//APPEND END
"""

        ret = parse_quiz_template(template_str)
        self.assertEqual(ret["prepend"], "aaa\n")
        self.assertEqual(ret["template"], "bbb\n")
        self.assertEqual(ret["append"], "ccc\n")

    def test_parse1(self):
        template_str = """
//PREPEND BEGIN
aaa
//PREPEND END

//APPEND BEGIN
ccc
//APPEND END
//APPEND BEGIN
ddd
//APPEND END
"""

        ret = parse_quiz_template(template_str)
        self.assertEqual(ret["prepend"], "aaa\n")
        self.assertEqual(ret["template"], "")
        self.assertEqual(ret["append"], "ccc\n")

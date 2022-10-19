import hashlib
import json
import os
# import shutil
import tempfile
import zipfile
from wsgiref.util import FileWrapper

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import StreamingHttpResponse, FileResponse

from account.decorators import quiz_permission_required, ensure_created_by
from contest.models import Contest, ContestStatus
from fps.parser import FPSHelper, FPSParser
from judge.dispatcher import SPJCompiler
from options.options import SysOptions
from submission.models import Submission, JudgeStatus
from utils.api import APIView, CSRFExemptAPIView, validate_serializer, APIError
from utils.constants import Difficulty
from utils.shortcuts import rand_str, natural_sort_key
from utils.tasks import delete_files
from ..models import Quiz, QuizRuleType, QuizTag
from ..serializers import (CreateContestQuizSerializer, CompileSPJSerializer,
                           CreateQuizSerializer, EditQuizSerializer, EditContestQuizSerializer,
                           QuizAdminSerializer, TestCaseUploadForm, ContestQuizMakePublicSerializer,
                           AddContestQuizSerializer, ExportQuizSerializer,
                           ExportQuizRequestSerialzier, UploadQuizForm, ImportQuizSerializer,
                           FPSQuizSerializer)
from ..utils import TEMPLATE_BASE, build_quiz_template

class QuizBase(APIView):
    def common_checks(self, request):
        data = request.data
        if data["spj"]:
            if not data["spj_language"] or not data["spj_code"]:
                return "Invalid spj"
            if not data["spj_compile_ok"]:
                return "SPJ code must be compiled successfully"
            data["spj_version"] = hashlib.md5(
                (data["spj_language"] + ":" + data["spj_code"]).encode("utf-8")).hexdigest()
        else:
            data["spj_language"] = None
            data["spj_code"] = None
        if data["rule_type"] == ProblemRuleType.OI:
            total_score = 0
            for item in data["test_case_score"]:
                if item["score"] <= 0:
                    return "Invalid score"
                else:
                    total_score += item["score"]
            data["total_score"] = total_score
        data["languages"] = list(data["languages"])

class QuizAPI(QuizBase):
    @quiz_permission_required
    @validate_serializer(CreateQuizSerializer)
    def post(self, request):
        data = request.data
        _id = data["_id"]
        if not _id:
            return self.error("Display ID is required")
        if Quiz.objects.filter(_id=_id, contest_id__isnull=True).exists():
            return self.error("Display ID already exists")

        error_info = self.common_checks(request)
        if error_info:
            return self.error(error_info)

        # todo check filename and score info
        tags = data.pop("tags")
        data["created_by"] = request.user
        quiz = Quiz.objects.create(**data)

        for item in tags:
            try:
                tag = QuizTag.objects.get(name=item)
            except QuizTag.DoesNotExist:
                tag = QuizTag.objects.create(name=item)
            quiz.tags.add(tag)
        return self.success(QuizAdminSerializer(quiz).data)

    @quiz_permission_required
    def get(self, request):
        quiz_id = request.GET.get("id")
        rule_type = request.GET.get("rule_type")
        user = request.user
        if quiz_id:
            try:
                quiz = Quiz.objects.get(id=quiz_id)
                ensure_created_by(quiz, request.user)
                return self.success(QuizAdminSerializer(quiz).data)
            except Quiz.DoesNotExist:
                return self.error("Quiz does not exist")

        quizs = Quiz.objects.filter(contest_id__isnull=True).order_by("-create_time")
        if rule_type:
            if rule_type not in QuizRuleType.choices():
                return self.error("Invalid rule_type")
            else:
                quizs = quizs.filter(rule_type=rule_type)

        keyword = request.GET.get("keyword", "").strip()
        if keyword:
            quizs = quizs.filter(Q(title__icontains=keyword) | Q(_id__icontains=keyword))
        if not user.can_mgmt_all_quiz():
            quizs = quizs.filter(created_by=user)
        return self.success(self.paginate_data(request, quizs, QuizAdminSerializer))

    @quiz_permission_required
    @validate_serializer(EditQuizSerializer)
    def put(self, request):
        data = request.data
        quiz_id = data.pop("id")

        try:
            quiz = Quiz.objects.get(id=quiz_id)
            ensure_created_by(quiz, request.user)
        except Quiz.DoesNotExist:
            return self.error("Quiz does not exist")

        _id = data["_id"]
        if not _id:
            return self.error("Display ID is required")
        if Quiz.objects.exclude(id=quiz_id).filter(_id=_id, contest_id__isnull=True).exists():
            return self.error("Display ID already exists")

        error_info = self.common_checks(request)
        if error_info:
            return self.error(error_info)
        # todo check filename and score info
        tags = data.pop("tags")
        data["languages"] = list(data["languages"])

        for k, v in data.items():
            setattr(quiz, k, v)
        quiz.save()

        quiz.tags.remove(*quiz.tags.all())
        for tag in tags:
            try:
                tag = QuizTag.objects.get(name=tag)
            except QuizTag.DoesNotExist:
                tag = QuizTag.objects.create(name=tag)
            quiz.tags.add(tag)

        return self.success()

    @quiz_permission_required
    def delete(self, request):
        id = request.GET.get("id")
        if not id:
            return self.error("Invalid parameter, id is required")
        try:
            quiz = Quiz.objects.get(id=id, contest_id__isnull=True)
        except Quiz.DoesNotExist:
            return self.error("Quiz does not exists")
        ensure_created_by(quiz, request.user)
        # d = os.path.join(settings.TEST_CASE_DIR, quiz.test_case_id)
        # if os.path.isdir(d):
        #     shutil.rmtree(d, ignore_errors=True)
        quiz.delete()
        return self.success()


class ContestQuizAPI(QuizBase):
    @validate_serializer(CreateContestQuizSerializer)
    def post(self, request):
        data = request.data
        try:
            contest = Contest.objects.get(id=data.pop("contest_id"))
            ensure_created_by(contest, request.user)
        except Contest.DoesNotExist:
            return self.error("Contest does not exist")

        if data["rule_type"] != contest.rule_type:
            return self.error("Invalid rule type")

        _id = data["_id"]
        if not _id:
            return self.error("Display ID is required")

        if Quiz.objects.filter(_id=_id, contest=contest).exists():
            return self.error("Duplicate Display id")

        error_info = self.common_checks(request)
        if error_info:
            return self.error(error_info)

        # todo check filename and score info
        data["contest"] = contest
        tags = data.pop("tags")
        data["created_by"] = request.user
        quiz = Quiz.objects.create(**data)

        for item in tags:
            try:
                tag = QuizTag.objects.get(name=item)
            except QuizTag.DoesNotExist:
                tag = QuizTag.objects.create(name=item)
            quiz.tags.add(tag)
        return self.success(QuizAdminSerializer(quiz).data)

    def get(self, request):
        quiz_id = request.GET.get("id")
        contest_id = request.GET.get("contest_id")
        user = request.user
        if quiz_id:
            try:
                quiz = Quiz.objects.get(id=quiz_id)
                ensure_created_by(quiz.contest, user)
            except Quiz.DoesNotExist:
                return self.error("Quiz does not exist")
            return self.success(QuizAdminSerializer(quiz).data)

        if not contest_id:
            return self.error("Contest id is required")
        try:
            contest = Contest.objects.get(id=contest_id)
            ensure_created_by(contest, user)
        except Contest.DoesNotExist:
            return self.error("Contest does not exist")
        quizs = Quiz.objects.filter(contest=contest).order_by("-create_time")
        if user.is_admin():
            quizs = quizs.filter(contest__created_by=user)
        keyword = request.GET.get("keyword")
        if keyword:
            quizs = quizs.filter(title__contains=keyword)
        return self.success(self.paginate_data(request, quizs, QuizAdminSerializer))

    @validate_serializer(EditContestQuizSerializer)
    def put(self, request):
        data = request.data
        user = request.user

        try:
            contest = Contest.objects.get(id=data.pop("contest_id"))
            ensure_created_by(contest, user)
        except Contest.DoesNotExist:
            return self.error("Contest does not exist")

        if data["rule_type"] != contest.rule_type:
            return self.error("Invalid rule type")

        quiz_id = data.pop("id")

        try:
            quiz = Quiz.objects.get(id=quiz_id, contest=contest)
        except Quiz.DoesNotExist:
            return self.error("Quiz does not exist")

        _id = data["_id"]
        if not _id:
            return self.error("Display ID is required")
        if Quiz.objects.exclude(id=quiz_id).filter(_id=_id, contest=contest).exists():
            return self.error("Display ID already exists")

        error_info = self.common_checks(request)
        if error_info:
            return self.error(error_info)
        # todo check filename and score info
        tags = data.pop("tags")
        data["languages"] = list(data["languages"])

        for k, v in data.items():
            setattr(quiz, k, v)
        quiz.save()

        quiz.tags.remove(*quiz.tags.all())
        for tag in tags:
            try:
                tag = QuizTag.objects.get(name=tag)
            except QuizTag.DoesNotExist:
                tag = QuizTag.objects.create(name=tag)
            quiz.tags.add(tag)
        return self.success()

    def delete(self, request):
        id = request.GET.get("id")
        if not id:
            return self.error("Invalid parameter, id is required")
        try:
            quiz = Quiz.objects.get(id=id, contest_id__isnull=False)
        except Quiz.DoesNotExist:
            return self.error("Quiz does not exists")
        ensure_created_by(quiz.contest, request.user)
        if Submission.objects.filter(quiz=quiz).exists():
            return self.error("Can't delete the quiz as it has submissions")
        # d = os.path.join(settings.TEST_CASE_DIR, quiz.test_case_id)
        # if os.path.isdir(d):
        #    shutil.rmtree(d, ignore_errors=True)
        quiz.delete()
        return self.success()


class MakeContestQuizPublicAPIView(APIView):
    @validate_serializer(ContestQuizMakePublicSerializer)
    @quiz_permission_required
    def post(self, request):
        data = request.data
        display_id = data.get("display_id")
        if Quiz.objects.filter(_id=display_id, contest_id__isnull=True).exists():
            return self.error("Duplicate display ID")

        try:
            quiz = Quiz.objects.get(id=data["id"])
        except Quiz.DoesNotExist:
            return self.error("Quiz does not exist")

        if not quiz.contest or quiz.is_public:
            return self.error("Already be a public quiz")
        quiz.is_public = True
        quiz.save()
        # https://docs.djangoproject.com/en/1.11/topics/db/queries/#copying-model-instances
        tags = quiz.tags.all()
        quiz.pk = None
        quiz.contest = None
        quiz._id = display_id
        quiz.visible = False
        quiz.submission_number = quiz.accepted_number = 0
        quiz.statistic_info = {}
        quiz.save()
        quiz.tags.set(tags)
        return self.success()


class AddContestQuizAPI(APIView):
    @validate_serializer(AddContestQuizSerializer)
    def post(self, request):
        data = request.data
        try:
            contest = Contest.objects.get(id=data["contest_id"])
            quiz = Quiz.objects.get(id=data["quiz_id"])
        except (Contest.DoesNotExist, Quiz.DoesNotExist):
            return self.error("Contest or Quiz does not exist")

        if contest.status == ContestStatus.CONTEST_ENDED:
            return self.error("Contest has ended")
        if Quiz.objects.filter(contest=contest, _id=data["display_id"]).exists():
            return self.error("Duplicate display id in this contest")

        tags = quiz.tags.all()
        quiz.pk = None
        quiz.contest = contest
        quiz.is_public = True
        quiz.visible = True
        quiz._id = request.data["display_id"]
        quiz.submission_number = quiz.accepted_number = 0
        quiz.statistic_info = {}
        quiz.save()
        quiz.tags.set(tags)
        return self.success()




class FPSQuizImport(CSRFExemptAPIView):
    request_parsers = ()

    def _create_quiz(self, quiz_data, creator):
        if quiz_data["time_limit"]["unit"] == "ms":
            time_limit = quiz_data["time_limit"]["value"]
        else:
            time_limit = quiz_data["time_limit"]["value"] * 1000
        template = {}
        prepend = {}
        append = {}
        for t in quiz_data["prepend"]:
            prepend[t["language"]] = t["code"]
        for t in quiz_data["append"]:
            append[t["language"]] = t["code"]
        for t in quiz_data["template"]:
            our_lang = lang = t["language"]
            if lang == "Python":
                our_lang = "Python3"
            template[our_lang] = TEMPLATE_BASE.format(prepend.get(lang, ""), t["code"], append.get(lang, ""))
        spj = quiz_data["spj"] is not None
        Quiz.objects.create(_id=f"fps-{rand_str(4)}",
                               title=quiz_data["title"],
                               description=quiz_data["description"],
                               input_description=quiz_data["input"],
                               output_description=quiz_data["output"],
                               hint=quiz_data["hint"],
                               test_case_score=quiz_data["test_case_score"],
                               time_limit=time_limit,
                               memory_limit=quiz_data["memory_limit"]["value"],
                               samples=quiz_data["samples"],
                               template=template,
                               rule_type=QuizRuleType.ACM,
                               source=quiz_data.get("source", ""),
                               spj=spj,
                               spj_code=quiz_data["spj"]["code"] if spj else None,
                               spj_language=quiz_data["spj"]["language"] if spj else None,
                               spj_version=rand_str(8) if spj else "",
                               visible=False,
                               languages=SysOptions.language_names,
                               created_by=creator,
                               difficulty=Difficulty.MID,
                               test_case_id=quiz_data["test_case_id"])

    def post(self, request):
        form = UploadQuizForm(request.POST, request.FILES)
        if form.is_valid():
            file = form.cleaned_data["file"]
            with tempfile.NamedTemporaryFile("wb") as tf:
                for chunk in file.chunks(4096):
                    tf.file.write(chunk)

                tf.file.flush()
                os.fsync(tf.file)

                quizs = FPSParser(tf.name).parse()
        else:
            return self.error("Parse upload file error")

        helper = FPSHelper()
        with transaction.atomic():
            for _quiz in quizs:
                test_case_id = rand_str()
                test_case_dir = os.path.join(settings.TEST_CASE_DIR, test_case_id)
                os.mkdir(test_case_dir)
                score = []
                for item in helper.save_test_case(_quiz, test_case_dir)["test_cases"].values():
                    score.append({"score": 0, "input_name": item["input_name"],
                                  "output_name": item.get("output_name")})
                quiz_data = helper.save_image(_quiz, settings.UPLOAD_DIR, settings.UPLOAD_PREFIX)
                s = FPSQuizSerializer(data=quiz_data)
                if not s.is_valid():
                    return self.error(f"Parse FPS file error: {s.errors}")
                quiz_data = s.data
                quiz_data["test_case_id"] = test_case_id
                quiz_data["test_case_score"] = score
                self._create_quiz(quiz_data, request.user)
        return self.success({"import_count": len(quizs)})

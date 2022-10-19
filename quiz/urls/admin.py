from django.conf.urls import url

from ..views.admin import (ContestQuizAPI, QuizAPI, MakeContestQuizPublicAPIView, AddContestQuizAPI,
                           FPSQuizImport)

urlpatterns = [
    url(r"^quiz/?$", QuizAPI.as_view(), name="quiz_admin_api"),
    url(r"^contest/quiz/?$", ContestQuizAPI.as_view(), name="contest_quiz_admin_api"),
    url(r"^contest_quiz/make_public/?$", MakeContestQuizPublicAPIView.as_view(), name="make_public_api"),
    url(r"^contest/add_quiz_from_public/?$", AddContestQuizAPI.as_view(), name="add_contest_quiz_from_public_api"),
    url(r"^import_fps/?$", FPSQuizImport.as_view(), name="fps_quiz_api"),
]

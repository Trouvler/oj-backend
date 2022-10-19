from django.conf.urls import url

from ..views.oj import QuizTagAPI, QuizAPI, ContestQuizAPI, PickOneAPI

urlpatterns = [
    url(r"^quiz/tags/?$", QuizTagAPI.as_view(), name="quiz_tag_list_api"),
    url(r"^quiz/?$", QuizAPI.as_view(), name="quiz_api"),
    url(r"^pickone/?$", PickOneAPI.as_view(), name="pick_one_api"),
    url(r"^contest/quiz/?$", ContestQuizAPI.as_view(), name="contest_quiz_api"),
]

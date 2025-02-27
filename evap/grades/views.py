from typing import List, Tuple

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models.query import QuerySet
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from evap.evaluation.auth import (
    grade_downloader_required,
    grade_publisher_or_manager_required,
    grade_publisher_required,
)
from evap.evaluation.models import Course, EmailTemplate, Evaluation, Semester
from evap.evaluation.tools import get_object_from_dict_pk_entry_or_logged_40x, ilen
from evap.grades.forms import GradeDocumentForm
from evap.grades.models import GradeDocument


@grade_publisher_required
def index(request):
    template_data = {
        "semesters": Semester.objects.filter(grade_documents_are_deleted=False),
        "disable_breadcrumb_grades": True,
    }
    return render(request, "grades_index.html", template_data)


def course_grade_document_count_tuples(courses: QuerySet[Course]) -> List[Tuple[Course, int, int]]:
    courses = courses.prefetch_related("degrees", "responsibles", "evaluations", "grade_documents")

    return [
        (
            course,
            ilen(gd for gd in course.grade_documents.all() if gd.type == GradeDocument.Type.MIDTERM_GRADES),
            ilen(gd for gd in course.grade_documents.all() if gd.type == GradeDocument.Type.FINAL_GRADES),
        )
        for course in courses
    ]


@grade_publisher_required
def semester_view(request, semester_id):
    semester = get_object_or_404(Semester, id=semester_id)
    if semester.grade_documents_are_deleted:
        raise PermissionDenied

    courses = (
        semester.courses.filter(evaluations__wait_for_grade_upload_before_publishing=True)
        .exclude(evaluations__state=Evaluation.State.NEW)
        .distinct()
    )
    courses = course_grade_document_count_tuples(courses)

    template_data = {
        "semester": semester,
        "courses": courses,
        "disable_if_archived": "disabled" if semester.grade_documents_are_deleted else "",
        "disable_breadcrumb_semester": True,
    }
    return render(request, "grades_semester_view.html", template_data)


@grade_publisher_or_manager_required
def course_view(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    semester = course.semester
    if semester.grade_documents_are_deleted:
        raise PermissionDenied

    template_data = {
        "semester": semester,
        "course": course,
        "grade_documents": course.grade_documents.all(),
        "disable_if_archived": "disabled" if semester.grade_documents_are_deleted else "",
        "disable_breadcrumb_course": True,
    }
    return render(request, "grades_course_view.html", template_data)


def on_grading_process_finished(course):
    evaluations = course.evaluations.all()
    if all(evaluation.state == Evaluation.State.REVIEWED for evaluation in evaluations):
        for evaluation in evaluations:
            assert evaluation.grading_process_is_finished
        for evaluation in evaluations:
            evaluation.publish()
            evaluation.save()

        EmailTemplate.send_participant_publish_notifications(evaluations)
        EmailTemplate.send_contributor_publish_notifications(evaluations)


@grade_publisher_required
def upload_grades(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    semester = course.semester
    if semester.grade_documents_are_deleted:
        raise PermissionDenied

    final_grades = request.GET.get("final") == "true"  # if parameter is not given, assume midterm grades

    grade_document = GradeDocument(course=course)
    if final_grades:
        grade_document.type = GradeDocument.Type.FINAL_GRADES
        grade_document.description_en = settings.DEFAULT_FINAL_GRADES_DESCRIPTION_EN
        grade_document.description_de = settings.DEFAULT_FINAL_GRADES_DESCRIPTION_DE
    else:
        grade_document.type = GradeDocument.Type.MIDTERM_GRADES
        grade_document.description_en = settings.DEFAULT_MIDTERM_GRADES_DESCRIPTION_EN
        grade_document.description_de = settings.DEFAULT_MIDTERM_GRADES_DESCRIPTION_DE

    form = GradeDocumentForm(request.POST or None, request.FILES or None, instance=grade_document)

    if form.is_valid():
        form.save(modifying_user=request.user)

        if final_grades:
            on_grading_process_finished(course)

        messages.success(request, _("Successfully uploaded grades."))
        return redirect("grades:course_view", course.id)

    template_data = {
        "semester": semester,
        "course": course,
        "form": form,
        "final_grades": final_grades,
        "show_automated_publishing_info": final_grades,
    }
    return render(request, "grades_upload_form.html", template_data)


@require_POST
@grade_publisher_required
def toggle_no_grades(request):
    course = get_object_from_dict_pk_entry_or_logged_40x(Course, request.POST, "course_id")
    if course.semester.grade_documents_are_deleted:
        raise PermissionDenied

    course.gets_no_grade_documents = not course.gets_no_grade_documents
    course.save()

    if course.gets_no_grade_documents:
        on_grading_process_finished(course)

    return HttpResponse()  # 200 OK


@require_GET
@grade_downloader_required
def download_grades(request, grade_document_id):
    grade_document = get_object_or_404(GradeDocument, id=grade_document_id)
    if grade_document.course.semester.grade_documents_are_deleted:
        raise PermissionDenied

    return FileResponse(grade_document.file.open(), filename=grade_document.filename(), as_attachment=True)


@grade_publisher_required
def edit_grades(request, grade_document_id):
    grade_document = get_object_or_404(GradeDocument, id=grade_document_id)
    course = grade_document.course
    semester = course.semester
    if semester.grade_documents_are_deleted:
        raise PermissionDenied

    form = GradeDocumentForm(request.POST or None, request.FILES or None, instance=grade_document)

    final_grades = (
        grade_document.type == GradeDocument.Type.FINAL_GRADES
    )  # if parameter is not given, assume midterm grades

    if form.is_valid():
        form.save(modifying_user=request.user)
        messages.success(request, _("Successfully updated grades."))
        return redirect("grades:course_view", course.id)

    template_data = {
        "semester": semester,
        "course": course,
        "form": form,
        "show_automated_publishing_info": False,
        "final_grades": final_grades,
    }
    return render(request, "grades_upload_form.html", template_data)


@require_POST
@grade_publisher_required
def delete_grades(request):
    grade_document = get_object_from_dict_pk_entry_or_logged_40x(GradeDocument, request.POST, "grade_document_id")
    grade_document.delete()
    return HttpResponse()  # 200 OK

from .list import student_list_view
from .detail import student_detail_view, class_student_detail_view
from .management import student_create_view, student_edit_view, update_student_points
from .enrollment import bulk_student_add, bulk_student_add_csv, remove_student_from_class
from .self_eval import student_goal_edit, lesson_report_tab, self_evaluation_edit
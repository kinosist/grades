from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    CustomUser, ClassRoom, LessonSession, 
    Group, GroupMember, Quiz, QuizScore, 
    PeerEvaluation, ContributionEvaluation,
    StudentQRCode, QRCodeScan, StudentLessonPoints
)
from .models import StudentClassPoints

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """統合ユーザー管理画面"""
    list_display = ('email', 'full_name', 'role', 'is_active', 'created_at')
    list_filter = ('role', 'is_active', 'created_at')
    search_fields = ('email', 'full_name', 'student_number', 'teacher_id')
    ordering = ('email',)
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('個人情報', {'fields': ('full_name', 'role', 'student_number', 'teacher_id')}),
        ('権限', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('重要な日付', {'fields': ('last_login', 'created_at', 'updated_at')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'full_name', 'role', 'student_number', 'teacher_id', 'password1', 'password2'),
        }),
    )
    readonly_fields = ('created_at', 'updated_at')

@admin.register(ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    """クラス管理画面"""
    list_display = ('class_name', 'year', 'semester', 'student_count')
    list_filter = ('year', 'semester')
    search_fields = ('class_name',)
    filter_horizontal = ('students', 'teachers')
    
    def student_count(self, obj):
        return obj.students.count()
    student_count.short_description = '学生数'

@admin.register(LessonSession)
class LessonSessionAdmin(admin.ModelAdmin):
    """授業回管理画面"""
    list_display = ('classroom', 'session_number', 'date', 'topic', 'has_quiz', 'has_peer_evaluation')
    list_filter = ('classroom', 'date', 'has_quiz', 'has_peer_evaluation')
    search_fields = ('topic', 'classroom__class_name')
    date_hierarchy = 'date'

@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    """グループ管理画面"""
    list_display = ('lesson_session', 'group_number', 'member_count')
    list_filter = ('lesson_session__classroom', 'lesson_session')
    search_fields = ('lesson_session__topic',)
    
    def member_count(self, obj):
        return obj.groupmember_set.count()
    member_count.short_description = 'メンバー数'

@admin.register(GroupMember)
class GroupMemberAdmin(admin.ModelAdmin):
    """グループメンバー管理画面"""
    list_display = ('group', 'student', 'role')
    list_filter = ('role', 'group__lesson_session')
    search_fields = ('student__full_name',)

@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    """小テスト管理画面"""
    list_display = ('quiz_name', 'lesson_session', 'grading_method', 'max_score')
    list_filter = ('grading_method', 'lesson_session__classroom')
    search_fields = ('quiz_name', 'lesson_session__topic')

@admin.register(QuizScore)
class QuizScoreAdmin(admin.ModelAdmin):
    """採点結果管理画面"""
    list_display = ('quiz', 'student', 'score', 'is_cancelled', 'graded_at')
    list_filter = ('is_cancelled', 'quiz__lesson_session', 'graded_at')
    search_fields = ('student__full_name', 'quiz__quiz_name')

@admin.register(PeerEvaluation)
class PeerEvaluationAdmin(admin.ModelAdmin):
    """ピア評価管理画面"""
    list_display = ('lesson_session', 'evaluator_group', 'first_place_group', 'second_place_group', 'created_at')
    list_filter = ('lesson_session', 'created_at')
    search_fields = ('lesson_session__topic',)

@admin.register(ContributionEvaluation)
class ContributionEvaluationAdmin(admin.ModelAdmin):
    """貢献度評価管理画面"""
    list_display = ('peer_evaluation', 'evaluatee', 'contribution_score')
    list_filter = ('contribution_score', 'peer_evaluation__lesson_session')
    search_fields = ('evaluatee__full_name',)


@admin.register(StudentQRCode)
class StudentQRCodeAdmin(admin.ModelAdmin):
    """学生QRコード管理画面"""
    list_display = ('student', 'qr_code_id', 'is_active', 'scan_count', 'created_at', 'last_used_at')
    list_filter = ('is_active', 'created_at', 'last_used_at')
    search_fields = ('student__full_name', 'student__student_number')
    readonly_fields = ('qr_code_id', 'created_at', 'last_used_at')
    
    def scan_count(self, obj):
        return obj.scans.count()
    scan_count.short_description = 'スキャン数'


@admin.register(QRCodeScan)
class QRCodeScanAdmin(admin.ModelAdmin):
    """QRコードスキャン履歴管理画面"""
    list_display = ('qr_code', 'scanned_by', 'points_awarded', 'scanned_at')
    list_filter = ('points_awarded', 'scanned_at', 'qr_code__student')
    search_fields = ('qr_code__student__full_name', 'scanned_by__full_name')
    readonly_fields = ('scanned_at',)


@admin.register(StudentLessonPoints)
class StudentLessonPointsAdmin(admin.ModelAdmin):
    """学生授業ポイント管理画面"""
    list_display = ('student', 'lesson_session', 'points', 'created_at', 'updated_at')
    list_filter = ('points', 'created_at', 'lesson_session__classroom')
    search_fields = ('student__full_name', 'lesson_session__classroom__class_name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(StudentClassPoints)
class StudentClassPointsAdmin(admin.ModelAdmin):
    """クラスごとの学生ポイント管理画面"""
    list_display = ('student', 'classroom', 'points', 'created_at', 'updated_at')
    list_filter = ('classroom', 'points', 'created_at')
    search_fields = ('student__full_name', 'classroom__class_name')
    readonly_fields = ('created_at', 'updated_at')

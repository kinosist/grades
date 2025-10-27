from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid


class CustomUserManager(BaseUserManager):
    """カスタムユーザーマネージャー"""
    def create_user(self, email, full_name, password=None, **extra_fields):
        if email:
            email = self.normalize_email(email)
        else:
            email = None
        
        user = self.model(email=email, full_name=full_name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, full_name, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'admin')
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, full_name, password, **extra_fields)


class CustomUser(AbstractUser):
    """統合ユーザーモデル（教員・学生共通）"""
    ROLE_CHOICES = [
        ('admin', '管理者'),
        ('teacher', '教員'),
        ('student', '学生'),
    ]
    
    username = None  # usernameフィールドを無効化
    email = models.EmailField(unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=100, verbose_name='氏名')
    furigana = models.CharField(max_length=100, blank=True, verbose_name='ふりがな')
    points = models.IntegerField(default=0, verbose_name='ポイント')
    role = models.CharField(
        max_length=10, 
        choices=ROLE_CHOICES, 
        default='student',
        verbose_name='役割'
    )
    student_number = models.CharField(max_length=20, blank=True, verbose_name='学籍番号')
    teacher_id = models.CharField(max_length=20, blank=True, verbose_name='教員ID')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='登録日時')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新日時')

    # AbstractUserのrelated_nameを設定
    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to.',
        related_name="customuser_set",
        related_query_name="customuser",
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name="customuser_set",
        related_query_name="customuser",
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']
    
    objects = CustomUserManager()

    class Meta:
        verbose_name = 'ユーザー'
        verbose_name_plural = 'ユーザー'

    def __str__(self):
        return self.full_name

    @property
    def is_teacher(self):
        return self.role in ['teacher', 'admin']
    
    @property
    def is_student(self):
        return self.role == 'student'


# 後方互換性のためのエイリアス
Teacher = CustomUser
Student = CustomUser


class ClassRoom(models.Model):
    """クラス管理"""
    SEMESTER_CHOICES = [
        ('first', '前期'),
        ('second', '後期'),
    ]
    
    class_name = models.CharField(max_length=100, verbose_name='クラス名')
    year = models.IntegerField(verbose_name='年度')
    semester = models.CharField(max_length=10, choices=SEMESTER_CHOICES, verbose_name='学期')
    teachers = models.ManyToManyField(Teacher, verbose_name='担当教員', related_name='classrooms')
    students = models.ManyToManyField(Student, blank=True, verbose_name='学生')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'クラス'
        verbose_name_plural = 'クラス'

    def __str__(self):
        return f"{self.year}年 {self.get_semester_display()} {self.class_name}"


class LessonSession(models.Model):
    """授業回マスタ"""
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, verbose_name='クラス')
    session_number = models.IntegerField(verbose_name='回数')
    date = models.DateField(verbose_name='実施日')
    topic = models.CharField(max_length=200, blank=True, verbose_name='テーマ・内容')
    has_quiz = models.BooleanField(default=False, verbose_name='小テストあり')
    has_peer_evaluation = models.BooleanField(default=False, verbose_name='ピア評価あり')
    peer_evaluation_closed = models.BooleanField(default=False, verbose_name='ピア評価締切済み')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '授業回'
        verbose_name_plural = '授業回'
        unique_together = ['classroom', 'session_number']

    def __str__(self):
        return f"{self.classroom.class_name} 第{self.session_number}回"


class Group(models.Model):
    """グループ"""
    lesson_session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, verbose_name='授業回')
    group_number = models.IntegerField(verbose_name='グループ番号')
    group_name = models.CharField(max_length=100, blank=True, verbose_name='グループ名', help_text='例: チーム虎、開発班A、など')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'グループ'
        verbose_name_plural = 'グループ'
        unique_together = ['lesson_session', 'group_number']

    def __str__(self):
        if self.group_name:
            return f"{self.lesson_session} {self.group_name}({self.group_number}グループ)"
        return f"{self.lesson_session} グループ{self.group_number}"

    @property
    def display_name(self):
        """表示用の名前を返す"""
        if self.group_name:
            return f"{self.group_name}"
        return f"{self.group_number}グループ"


class GroupMember(models.Model):
    """グループメンバー"""
    group = models.ForeignKey(Group, on_delete=models.CASCADE, verbose_name='グループ')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name='学生', related_name='group_memberships')
    role = models.CharField(max_length=50, blank=True, verbose_name='役割')

    class Meta:
        verbose_name = 'グループメンバー'
        verbose_name_plural = 'グループメンバー'
        unique_together = ['group', 'student']

    def __str__(self):
        return f"{self.group} - {self.student.full_name}"


class Quiz(models.Model):
    """小テスト"""
    GRADING_METHOD_CHOICES = [
        ('pass_fail', '合否'),
        ('numeric', '数値入力'),
        ('rubric', 'ルーブリック'),
        ('qr_mobile', 'QRコード巡回採点'),
    ]
    
    lesson_session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, verbose_name='授業回')
    quiz_name = models.CharField(max_length=100, verbose_name='小テスト名')
    max_score = models.IntegerField(verbose_name='満点')
    grading_method = models.CharField(
        max_length=20, 
        choices=GRADING_METHOD_CHOICES, 
        default='numeric', 
        verbose_name='採点方式'
    )
    quick_buttons = models.JSONField(null=True, blank=True, verbose_name='クイックボタン設定')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '小テスト'
        verbose_name_plural = '小テスト'

    def __str__(self):
        return f"{self.lesson_session} - {self.quiz_name}"


class QuizScore(models.Model):
    """小テスト採点結果"""
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, verbose_name='小テスト')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name='学生', related_name='quiz_scores_as_student')
    score = models.IntegerField(verbose_name='得点')
    graded_by = models.ForeignKey(Teacher, on_delete=models.CASCADE, verbose_name='採点者', related_name='quiz_scores_graded')
    is_cancelled = models.BooleanField(default=False, verbose_name='取り消し済み')
    graded_at = models.DateTimeField(auto_now_add=True, verbose_name='採点日時')

    class Meta:
        verbose_name = '小テスト結果'
        verbose_name_plural = '小テスト結果'

    def __str__(self):
        return f"{self.quiz} - {self.student.full_name}: {self.score}点"


class Question(models.Model):
    """小テストの問題"""
    QUESTION_TYPE_CHOICES = [
        ('multiple_choice', '選択問題'),
        ('true_false', '正誤問題'),
        ('short_answer', '記述問題'),
    ]
    
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, verbose_name='小テスト', related_name='questions')
    question_text = models.TextField(verbose_name='問題文')
    question_type = models.CharField(
        max_length=20,
        choices=QUESTION_TYPE_CHOICES,
        default='multiple_choice',
        verbose_name='問題形式'
    )
    points = models.IntegerField(default=1, verbose_name='配点')
    order = models.IntegerField(default=1, verbose_name='出題順')
    correct_answer = models.TextField(blank=True, verbose_name='正解（記述問題用）')
    
    class Meta:
        verbose_name = '問題'
        verbose_name_plural = '問題'
        ordering = ['order']
    
    def __str__(self):
        return f"{self.quiz.quiz_name} - 問題{self.order}"


class QuestionChoice(models.Model):
    """問題の選択肢"""
    question = models.ForeignKey(Question, on_delete=models.CASCADE, verbose_name='問題', related_name='choices')
    choice_text = models.CharField(max_length=500, verbose_name='選択肢')
    is_correct = models.BooleanField(default=False, verbose_name='正解')
    order = models.IntegerField(default=1, verbose_name='表示順')
    
    class Meta:
        verbose_name = '選択肢'
        verbose_name_plural = '選択肢'
        ordering = ['order']
    
    def __str__(self):
        return f"{self.question} - {self.choice_text}"


class PeerEvaluation(models.Model):
    """ピア評価"""
    lesson_session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, verbose_name='授業回')
    evaluator_token = models.UUIDField(verbose_name='評価者トークン（匿名化）')
    evaluator_group = models.ForeignKey(
        Group, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='peer_evaluations_as_evaluator',
        verbose_name='評価者グループ'
    )
    first_place_group = models.ForeignKey(
        Group, 
        on_delete=models.CASCADE, 
        related_name='first_place_votes', 
        verbose_name='1位グループ'
    )
    second_place_group = models.ForeignKey(
        Group, 
        on_delete=models.CASCADE, 
        related_name='second_place_votes', 
        verbose_name='2位グループ'
    )
    first_place_reason = models.TextField(blank=True, verbose_name='1位選択理由')
    second_place_reason = models.TextField(blank=True, verbose_name='2位選択理由')
    class_comment = models.TextField(blank=True, verbose_name='授業コメント')
    general_comment = models.TextField(blank=True, verbose_name='全般コメント')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='評価日時')

    class Meta:
        verbose_name = 'ピア評価'
        verbose_name_plural = 'ピア評価'

    def __str__(self):
        return f"{self.lesson_session} - 匿名評価 ({self.created_at.strftime('%m/%d %H:%M')})"


class ContributionEvaluation(models.Model):
    """貢献度評価"""
    peer_evaluation = models.ForeignKey(PeerEvaluation, on_delete=models.CASCADE, verbose_name='ピア評価')
    evaluatee = models.ForeignKey(
        Student, 
        on_delete=models.CASCADE, 
        related_name='contributioneval_evaluatee',
        verbose_name='被評価者'
    )
    contribution_score = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name='貢献度スコア'
    )

    class Meta:
        verbose_name = '貢献度評価'
        verbose_name_plural = '貢献度評価'
        unique_together = ['peer_evaluation', 'evaluatee']

    def __str__(self):
        return f"{self.peer_evaluation} - {self.evaluatee.full_name}: {self.contribution_score}点"


class Attendance(models.Model):
    """出席情報"""
    ATTENDANCE_STATUS_CHOICES = [
        ('present', '出席'),
        ('absent', '欠席'),
        ('late', '遅刻'),
        ('early_leave', '早退'),
    ]
    
    lesson_session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, verbose_name='授業回')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name='学生', related_name='attendances')
    status = models.CharField(
        max_length=20,
        choices=ATTENDANCE_STATUS_CHOICES,
        default='present',
        verbose_name='出席状況'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = '出席情報'
        verbose_name_plural = '出席情報'
        unique_together = ['lesson_session', 'student']
    
    def __str__(self):
        return f"{self.lesson_session} - {self.student.full_name}: {self.get_status_display()}"


class StudentQRCode(models.Model):
    """学生QRコード"""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name='学生', related_name='qr_codes')
    qr_code_id = models.UUIDField(default=uuid.uuid4, unique=True, verbose_name='QRコードID')
    is_active = models.BooleanField(default=True, verbose_name='有効')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='作成日時')
    last_used_at = models.DateTimeField(null=True, blank=True, verbose_name='最終使用日時')
    
    class Meta:
        verbose_name = '学生QRコード'
        verbose_name_plural = '学生QRコード'
    
    def __str__(self):
        return f"{self.student.full_name}のQRコード"
    
    @property
    def qr_code_url(self):
        """QRコードのURLを生成"""
        from django.urls import reverse
        return reverse('qr_code_scan', kwargs={'qr_code_id': self.qr_code_id})


class QRCodeScan(models.Model):
    """QRコードスキャン履歴"""
    qr_code = models.ForeignKey(StudentQRCode, on_delete=models.CASCADE, verbose_name='QRコード', related_name='scans')
    scanned_by = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name='スキャン者', related_name='qr_scans')
    lesson_session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, verbose_name='授業セッション', related_name='qr_scans', null=True, blank=True)
    points_awarded = models.IntegerField(default=1, verbose_name='付与ポイント')
    scanned_at = models.DateTimeField(auto_now_add=True, verbose_name='スキャン日時')
    
    class Meta:
        verbose_name = 'QRコードスキャン'
        verbose_name_plural = 'QRコードスキャン'
        # unique_together制約を削除 - 何度でもスキャン可能にする
    
    def __str__(self):
        return f"{self.qr_code.student.full_name}のQRコードを{self.scanned_by.full_name}がスキャン"


class StudentLessonPoints(models.Model):
    """学生の授業ごとのポイント管理"""
    student = models.ForeignKey(CustomUser, on_delete=models.CASCADE, verbose_name='学生', related_name='lesson_points')
    lesson_session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, verbose_name='授業セッション', related_name='student_points')
    points = models.IntegerField(default=0, verbose_name='ポイント')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='作成日時')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新日時')
    
    class Meta:
        verbose_name = '学生授業ポイント'
        verbose_name_plural = '学生授業ポイント'
        unique_together = ['student', 'lesson_session']  # 同じ学生の同じ授業セッションは1つのレコードのみ
    
    def __str__(self):
        return f"{self.student.full_name} - {self.lesson_session.classroom.class_name} 第{self.lesson_session.session_number}回 ({self.lesson_session.date}) - {self.points}pt"


class StudentClassPoints(models.Model):
    """学生ごとのクラス単位のポイント管理"""
    student = models.ForeignKey(CustomUser, on_delete=models.CASCADE, verbose_name='学生', related_name='class_points')
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, verbose_name='クラス', related_name='student_class_points')
    points = models.IntegerField(default=0, verbose_name='ポイント')
    attendance_rate = models.FloatField(default=0.0, verbose_name='出席率', help_text='0-100の範囲')
    attendance_points = models.FloatField(default=0.0, verbose_name='出席点', help_text='出席率から計算される点数')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='作成日時')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新日時')

    class Meta:
        verbose_name = '学生クラスポイント'
        verbose_name_plural = '学生クラスポイント'
        unique_together = ['student', 'classroom']

    def __str__(self):
        return f"{self.student.full_name} - {self.classroom.class_name} - {self.points}pt"

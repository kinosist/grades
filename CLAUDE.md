# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Django 5.2.5 web application for educational institutions (学校管理システム). Uses `uv` for package management. SQLite3 database in development.

## Development Commands

### Environment Setup
```powershell
uv sync                              # Install dependencies
uv run python manage.py migrate      # Apply database migrations
uv run python manage.py createsuperuser # Create admin user (email as username)
```

### Development Server
```powershell
uv run python manage.py runserver    # Start at http://127.0.0.1:8000/
```

### Database Management
```powershell
uv run python manage.py makemigrations  # Create migration files
uv run python manage.py migrate         # Apply migrations
uv run python manage.py dbshell         # Access database shell
uv run python manage.py shell           # Django Python shell
```

### Test Data
```powershell
uv run python test_login.py            # Test login functionality
uv run python create_test_users.py     # Create test user data
```

## Architecture

### Project Structure
- **`school_project/`**: Django settings and root URL configuration
- **`school_management/`**: Main application with all business logic
  - `models.py`: All data models (unified CustomUser, ClassRoom, LessonSession, Group, Quiz, PeerEvaluation, etc.)
  - `views.py`: View logic for all features
  - `urls.py`: URL routing (app_name='school_management')
  - `templates/school_management/`: All HTML templates

### User Model Architecture
**Critical**: Uses `CustomUser` (extends `AbstractUser`) as the unified user model:
- `AUTH_USER_MODEL = 'school_management.CustomUser'` in settings
- Email-based authentication (`USERNAME_FIELD = 'email'`)
- Role-based system: `role` field with choices: 'admin', 'teacher', 'student'
- Both `Teacher` and `Student` are aliases pointing to `CustomUser` for backward compatibility
- Properties: `is_teacher` (admin/teacher), `is_student` (student)
- Students have `student_number`, teachers have `teacher_id`
- Points system: `points` field for gamification, per-lesson tracking via `StudentLessonPoints`, per-class via `StudentClassPoints`

### Core Feature Models
**ClassRoom**: Year/semester-based classes with many-to-many relationships to teachers and students

**LessonSession**: Individual lesson instances within a classroom
- Tracks session number, date, topic
- Flags: `has_quiz`, `has_peer_evaluation`, `peer_evaluation_closed`
- One-to-many with Group, Quiz, PeerEvaluation

**Group**: Work groups within lesson sessions
- Has `group_number`, optional `group_name`
- Members tracked via `GroupMember` model with optional roles

**Quiz System**:
- Quiz model with grading methods: pass_fail, numeric, rubric, qr_mobile
- `QuizScore` for results (with `is_cancelled` flag for corrections)
- `Question` and `QuestionChoice` for quiz content (multiple_choice, true_false, short_answer)
- JSON field `quick_buttons` for grading shortcuts

**Peer Evaluation**:
- `PeerEvaluation`: Anonymous voting (UUID token) for 1st/2nd place groups with reasons
- `ContributionEvaluation`: 1-5 scale rating for group member contributions
- Linked to evaluator's group via `evaluator_group`

**QR Code System**:
- `StudentQRCode`: UUID-based QR codes for each student
- `QRCodeScan`: Scan history with point awards and duplicate prevention

### URL Patterns
Key route patterns (`app_name='school_management'`):
- `/`: Login (email-based)
- `/dashboard/`: Teacher dashboard
- `/student-dashboard/`: Student dashboard
- `/classes/`: Class management
- `/classes/<id>/students/select/`: Bulk student enrollment
- `/classes/<id>/sessions/`: Lesson session management
- `/sessions/<id>/quizzes/`: Quiz creation and grading
- `/lesson-sessions/<id>/groups/`: Group management
- `/lesson-sessions/<id>/peer-evaluation/`: Peer evaluation setup
- `/peer-evaluation/<token>/`: Anonymous student evaluation form
- `/students/`: Student master list management
- `/qr-codes/`: QR code generation and scanning

### Authentication & Access Control
- Custom user manager (`CustomUserManager`) handles user creation
- Login redirects: `LOGIN_REDIRECT_URL = '/dashboard/'`
- Role-based views: Check `user.is_teacher` or `user.is_student`
- Students access via token-based URLs for peer evaluations (anonymous)

### Key Design Patterns
- Unique constraints: `(classroom, session_number)`, `(lesson_session, group_number)`, `(peer_evaluation, evaluatee)`
- CASCADE deletion for referential integrity
- Many-to-many with intermediate models: `GroupMember` for role assignment
- UUID tokens for anonymous peer evaluation
- Points are tracked both globally on CustomUser and per-lesson/per-class via separate models
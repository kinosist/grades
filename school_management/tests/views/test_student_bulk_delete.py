from django.test import TestCase
from django.urls import reverse
from school_management.models import CustomUser, TeacherStudentAssignment

class StudentBulkDeleteTest(TestCase):
    def setUp(self):
        # Create a teacher
        self.teacher = CustomUser.objects.create_user(
            email='teacher@example.com',
            full_name='Teacher One',
            password='password123',
            role='teacher',
        )
        
        # Create 35 students managed by this teacher
        self.students = []
        for i in range(1, 36):
            student = CustomUser.objects.create_user(
                email=f'student{i}@example.com',
                full_name=f'Student {i:02d}',
                password='password123',
                role='student',
                student_number=f'S{i:03d}',
            )
            TeacherStudentAssignment.assign(self.teacher, student)
            self.students.append(student)
            
        self.client.login(email='teacher@example.com', password='password123')

    def test_bulk_delete_confirm_single_page(self):
        # Select first 5 students manually
        selected_ids = [s.id for s in self.students[:5]]
        selected_ids_str = ','.join(map(str, selected_ids))
        
        response = self.client.post(
            reverse('school_management:student_bulk_delete_confirm'),
            {'student_ids': selected_ids_str}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 5)
        self.assertEqual(response.context['student_ids'], selected_ids_str)

    def test_bulk_delete_confirm_select_all_pages(self):
        # Select all pages across pagination
        response = self.client.post(
            reverse('school_management:student_bulk_delete_confirm'),
            {
                'student_ids': '',
                'select_all_pages': 'true',
                'search_query': ''
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 35)
        
        # Verify all 35 student IDs are in the returned student_ids string
        returned_ids = [int(sid) for sid in response.context['student_ids'].split(',')]
        self.assertEqual(len(returned_ids), 35)
        all_ids = [s.id for s in self.students]
        self.assertEqual(set(returned_ids), set(all_ids))

    def test_bulk_delete_confirm_select_all_pages_with_search(self):
        # Select all pages with a search filter that matches students 01 to 09 (due to formatting "Student 0X")
        response = self.client.post(
            reverse('school_management:student_bulk_delete_confirm'),
            {
                'student_ids': '',
                'select_all_pages': 'true',
                'search_query': 'Student 0'
            }
        )
        self.assertEqual(response.status_code, 200)
        # Expected matches: Student 01 through Student 09 (9 students)
        self.assertEqual(response.context['total_count'], 9)
        
        returned_ids = [int(sid) for sid in response.context['student_ids'].split(',')]
        self.assertEqual(len(returned_ids), 9)
        expected_ids = [s.id for s in self.students[:9]]
        self.assertEqual(set(returned_ids), set(expected_ids))

    def test_bulk_delete_confirm_select_all_pages_with_exclusions(self):
        # Select all pages, but exclude student 1 and student 2 (first 2 students)
        deselected_ids = [self.students[0].id, self.students[1].id]
        deselected_ids_str = ','.join(map(str, deselected_ids))
        
        response = self.client.post(
            reverse('school_management:student_bulk_delete_confirm'),
            {
                'student_ids': '',
                'select_all_pages': 'true',
                'search_query': '',
                'deselected_student_ids': deselected_ids_str
            }
        )
        self.assertEqual(response.status_code, 200)
        # 35 total - 2 excluded = 33
        self.assertEqual(response.context['total_count'], 33)
        
        returned_ids = [int(sid) for sid in response.context['student_ids'].split(',')]
        self.assertEqual(len(returned_ids), 33)
        self.assertNotIn(self.students[0].id, returned_ids)
        self.assertNotIn(self.students[1].id, returned_ids)

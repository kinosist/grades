#!/usr/bin/env python
"""
Database migration script with retry logic for Railway deployment.
Handles transient connection errors during deployment.
"""
import os
import sys
import time
import django
from django.core.management import execute_from_command_line

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_project.settings')
django.setup()

def run_migrations_with_retry(max_retries=5, initial_delay=2):
    """
    Run Django migrations with exponential backoff retry logic.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds (will be doubled each retry)
    """
    from django.db import connection
    from django.core.management import call_command

    delay = initial_delay

    for attempt in range(max_retries):
        try:
            print(f"Migration attempt {attempt + 1}/{max_retries}...")

            # Test database connection first
            print("Testing database connection...")
            connection.ensure_connection()
            print("Database connection successful!")

            # Run migrations
            print("Running migrations...")
            call_command('migrate', '--noinput', verbosity=1)
            print("Migrations completed successfully!")
            return True

        except Exception as e:
            error_msg = str(e)
            print(f"Migration attempt {attempt + 1} failed: {error_msg}")

            if attempt < max_retries - 1:
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)
                delay *= 2  # Exponential backoff

                # Close any existing connections before retry
                try:
                    connection.close()
                except:
                    pass
            else:
                print(f"All {max_retries} migration attempts failed!")
                raise

    return False

if __name__ == '__main__':
    try:
        success = run_migrations_with_retry()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Fatal error during migration: {e}")
        sys.exit(1)

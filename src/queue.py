import peewee as pw
from datetime import datetime

db = pw.SqliteDatabase('analysis.db')

class BaseModel(pw.Model):
    class Meta:
        database = db

class Submission(BaseModel):
    submission_id = pw.CharField()
    task_data = pw.TextField()
    current_step = pw.CharField()
    current_run = pw.IntegerField(null=True)
    task_status = pw.CharField()
    created_at = pw.DateTimeField(default=datetime.now)
    updated_at = pw.DateTimeField(default=datetime.now)
    started_at = pw.DateTimeField(null=True)
    completed_at = pw.DateTimeField(null=True)
    user_id = pw.IntegerField()  # User who submitted the task
    analysis_type = pw.CharField()

    class Meta:
        table_name = "analysis_queue"
        indexes = (
            (('submission_id', 'task_status'), False),
        )


class AnalysisRun(BaseModel):
    analysis_queue = pw.ForeignKeyField(Submission, backref='runs', on_delete='CASCADE')
    step_name = pw.CharField()
    attempt_number = pw.IntegerField(default=1)
    status = pw.CharField()
    started_at = pw.DateTimeField(default=datetime.now)
    completed_at = pw.DateTimeField(null=True)
    requires_user_input = pw.BooleanField(default=False)
    user_input = pw.TextField(null=True)
    error_message = pw.TextField(null=True)

    class Meta:
        table_name = "analysis_run"


# Initialize tables
def initialize_tables():
    with db:
        db.create_tables([Submission, AnalysisRun])


if __name__ == '__main__':
    initialize_tables()
    print("Tables created successfully.")

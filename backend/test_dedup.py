from backend.guided_questions import generate_questions
from backend.service_builder import deduplicate_questions

q = generate_questions(["EC2", "S3", "RDS", "Lambda", "DynamoDB"])
print("Before: ", len(q))
filtered, inferred = deduplicate_questions(q, {}, {})
print("After: ", len(filtered))

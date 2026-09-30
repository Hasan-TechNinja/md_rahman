from django.utils.crypto import get_random_string


def generate_uid(
    instance,
    field_name: str,
    prefix: str = "store",
    length: int = 8,
    allowed_chars: str = "0123456789",
):
  """
  Universal UID generator.

  Example output: store12345678

  - instance: model instance (self)
  - field_name: the model field you want to fill (e.g. "store_id", "ref_code", "vendor_code")
  - prefix: string prefix before digits
  - length: number of random chars (<= 8 for your case)
  - allowed_chars: defaults to digits only
  """

  if length > 8:
    length = 8  # enforce your rule: under 8 digits

  Model = instance.__class__

  while True:
    code = f"{prefix}{get_random_string(length, allowed_chars)}"

    # Check uniqueness on the given field_name
    if not Model.objects.filter(**{field_name: code}).exists():
      return code
import random
import string
from datetime import timedelta

from django.core.mail import send_mail
from django.utils import timezone

from laundrymart import settings


def send_otp_for_email_verification(email, otp):
  subject = "Verification Code for Email registration"
  plain_message = f'Your verification code is {otp}. Expires in 1 minute.'
  html_message = f'''
    <html>
      <body>
        <p>Your verification code is <strong style="color: green;">{otp}</strong>.</p>
        <p>Expires in 1 minute.</p>
      </body>
    </html>
  '''
  email_from = settings.EMAIL_HOST_USER
  send_mail(subject, plain_message, email_from, [email], html_message=html_message, fail_silently=True)

def send_otp_for_sms_verification(phone_number, otp):
  pass

def send_otp_for_sms_password(phone_number, otp):
  pass

def send_otp_for_password(email, otp):
  subject = "Verification Code for Resetting Password"
  plain_message = f'Your verification code is {otp}. Expires in 3 minute.'
  html_message = f'''
    <html>
      <body>
        <p>Your verification code is <strong style="color: green;">{otp}</strong>.</p>
        <p>Expires in 1 minute.</p>
      </body>
    </html>
  '''
  email_from = settings.EMAIL_HOST_USER  # should be EMAIL_HOST_USER, not EMAIL_HOST
  send_mail(subject, plain_message, email_from, [email], html_message=html_message, fail_silently=True)

def generate_otp(length=4):
  """Generate a random OTP of the given length."""
  return ''.join(random.choices(string.digits, k=length))


def send_otp_for_admin_verification(laundrymart_admin, otp):
  """
  Sends OTP to the laundrymart admin for employee verification.
  """
  subject = "Verification Code for Employee Login"
  plain_message = f'Your employee verification OTP is {otp}. Expires in 5 minutes.'
  html_message = f'''
        <html>
            <body>
                <p>Your employee verification OTP is <strong style="color: green;">{otp}</strong>.</p>
                <p>Expires in 5 minutes.</p>
            </body>
        </html>
    '''
  email_from = settings.EMAIL_HOST_USER
  send_mail(subject, plain_message, email_from, [laundrymart_admin.email], html_message=html_message,
            fail_silently=True)

  # Store OTP and expiration time for the admin
  laundrymart_admin.otp = otp
  laundrymart_admin.otp_expires = timezone.now() + timedelta(minutes=5)
  laundrymart_admin.save()
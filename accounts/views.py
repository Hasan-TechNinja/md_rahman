import random
from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response

from rest_framework import serializers, status
from rest_framework_simplejwt.views import TokenObtainPairView

from laundrymart.permissions import IsCustomer, IsEmployee, IsStaff
from message_utils.email_utils import generate_otp, send_otp_for_admin_verification, send_otp_for_email_verification, \
  send_otp_for_password, \
  send_otp_for_sms_password, send_otp_for_sms_verification
from messaging.models import Room
from .employee_tokens import EmployeeRefreshToken
from .models import Employee, LaundrymartStore, SecondaryLocation, User
from .serializers import CreateUserSerializer, CustomerProfileSerializer, CustomerSettingSerializer, \
  EmployeeLoginSerializer, ForgetPasswordSerializer, LogoutSerializer, \
  OTPSerializer, \
  ResendOTPSerializer, \
  ChangePasswordSerializer, SecondaryLocationSerializer, VendorProfileSerializer, VendorSettingSerializer
from drf_spectacular.utils import OpenApiExample, OpenApiRequest, extend_schema, OpenApiResponse, inline_serializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated, AllowAny
import logging
logger = logging.getLogger(__name__)

@staff_member_required
def my_admin_profile(request):
    # Redirects to current user's change form
    return redirect(reverse("admin:accounts_user_change", args=[request.user.pk]))
class RegisterView(APIView):

  @extend_schema(
    request=CreateUserSerializer,
    responses={201: None, 400: 'Validation Error'}
  )
  def post(self, request):
    email = request.data.get('email')
    phone_number = request.data.get('phone_number')

    email = email.strip().lower() if email else None
    phone_number = phone_number.strip() if phone_number else None
    logger.info(email, phone_number)

    if not email and not phone_number:
      return Response(
        {"error": "Either email or phone number must be provided."},
        status=status.HTTP_400_BAD_REQUEST
      )

    # Build query dynamically (no null/blank traps)
    query = Q()
    if email:
      query |= Q(email=email)
    if phone_number:
      query |= Q(phone_number=phone_number)

    existing_user = User.objects.filter(query).first()
    logger.info(existing_user)

    if existing_user:
      if existing_user.is_active and existing_user.is_verified:
        identifier = email or phone_number
        return Response(
          {"error": f"{identifier}: An account with this identifier already exists and is active."},
          status=status.HTTP_400_BAD_REQUEST
        )
    with transaction.atomic():
      # Safe to delete only after validation passes
      if existing_user:
        existing_user.delete()

    serializer = CreateUserSerializer(data=request.data)

    if not serializer.is_valid():
      errors = serializer.errors
      field, messages = next(iter(errors.items()))
      readable_field = field.replace('_', ' ').capitalize()
      first_message = messages[0] if isinstance(messages, list) else messages
      logger.error({"error": f"{readable_field}: {first_message}"})
      return Response(
        {"error": f"{readable_field}: {first_message}"},
        status=status.HTTP_400_BAD_REQUEST
      )

    # Proceed with serialization and user creation
    serializer = CreateUserSerializer(data=request.data)
    if serializer.is_valid():
      user = serializer.save()

    # Send OTP
    if user.email:
      send_otp_for_email_verification(user.email, user.otp)
      message = "OTP sent to email."
    elif user.phone_number:
      send_otp_for_sms_verification(user.phone_number, user.otp)
      message = "OTP sent to phone number."
    else:
      message = "OTP generated but no delivery method available."

    return Response({'message': message}, status=status.HTTP_201_CREATED)



class VerifyOTPView(APIView):
  @extend_schema(
    request=OTPSerializer,
    responses={
      200: OpenApiResponse(description='OTP verified successfully with tokens'),
      400: OpenApiResponse(description='Invalid or expired OTP'),
      404: OpenApiResponse(description='User not found'),
    }
  )
  def patch(self, request):
    serializer = OTPSerializer(data=request.data)
    if not serializer.is_valid():
      errors = serializer.errors
      field, messages = next(iter(errors.items()))
      readable_field = field.replace('_', ' ').capitalize()
      first_message = messages[0] if isinstance(messages, list) else messages
      error_message = f"{readable_field}: {first_message}"
      return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

    email = serializer.validated_data.get('email')
    phone_number = serializer.validated_data.get('phone_number')
    otp = serializer.validated_data.get('otp')

    # Find user by email or phone
    user = None
    if email:
      user = User.objects.filter(email=email).first()
    elif phone_number:
      user = User.objects.filter(phone_number=phone_number).first()

    if not user:
      return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

    # Check OTP validity
    if user.otp != otp:
      return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)

    if not user.otp_expires or user.otp_expires < timezone.now():
      return Response({'error': 'OTP expired'}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
      room_created = False

      # Check if the user is inactive and a non-staff user (we only need to create the room if inactive)
      if not user.is_staff and not user.is_active:
        superuser_ids = User.objects.filter(is_superuser=True).values_list('id', flat=True)
        participants_ids = [user.id] + list(superuser_ids)

        # First try to find existing room with these exact participants
        room = Room.objects.filter(
          name=f'Admin Chatroom',
          participants__id__in=participants_ids
        ).filter(  # make sure it has exactly these participants and no more
          ~Q(participants__id__in=User.objects.exclude(id__in=participants_ids))
        ).distinct().first()

        if room is None:
          room = Room.objects.create(name='Admin Chatroom')
          room.participants.add(*participants_ids)
          room_created = True
        else:
          room_created = False

      # Update the user details
      user.is_active = True
      user.is_verified = True
      user.otp = None
      user.otp_expires = None
      user.last_login = timezone.now()
      user.save(update_fields=['is_active', 'is_verified', 'otp', 'otp_expires', 'last_login'])

    # Generate JWT tokens
    refresh = RefreshToken.for_user(user)
    access = refresh.access_token

    data = {
      "message": "Otp Verification successful.",
      "user": {
        "id": user.id,
        "email": user.email,
        "phone_number": user.phone_number,
        "full_name": user.full_name,
        "role": 'Customer' if not user.is_staff else 'Vendor'
      },
      "tokens": {
        "refresh": str(refresh),
        "access": str(access)
      }
    }

    if room_created:
        data["message"] = "Otp Verification successful and Admin Chatroom created."

    return Response(data, status=status.HTTP_200_OK)

class ResendOTPView(APIView):
  @extend_schema(
    request=ResendOTPSerializer,
    responses={200: OpenApiResponse(description='OTP resent successfully'), 404: OpenApiResponse(description='Inactive user not found')}
  )
  def post(self, request):
    serializer = ResendOTPSerializer(data=request.data)
    if not serializer.is_valid():
      errors = serializer.errors
      field, messages = next(iter(errors.items()))
      readable_field = field.replace('_', ' ').capitalize()
      first_message = messages[0] if isinstance(messages, list) else messages
      error_message = f"{readable_field}: {first_message}"
      return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

    email = serializer.validated_data.get('email')
    phone_number = serializer.validated_data.get('phone_number')

    with transaction.atomic():
      user = None
      if email:
        user = User.objects.filter(email=email).first()
      elif phone_number:
        user = User.objects.filter(phone_number=phone_number).first()

      if not user:
        return Response(
          {'error': 'Inactive user not found with that identifier.'},
          status=status.HTTP_404_NOT_FOUND
        )

      # Generate new OTP
      otp = random.randint(1000, 9999)
      otp_expiry = timezone.now() + timedelta(minutes=1)

      user.otp = str(otp)
      user.otp_expires = otp_expiry
      user.save(update_fields=['otp', 'otp_expires'])

      # Send OTP via correct channel
      if user.email:
        send_otp_for_email_verification(user.email, otp)
        message = 'OTP resent to email.'
      elif user.phone_number:
        send_otp_for_sms_verification(user.phone_number, otp)
        message = 'OTP resent to phone number.'
      else:
        message = 'OTP generated but no delivery method available.'

      return Response({'message': message}, status=status.HTTP_200_OK)

class ChangePasswordAPIView(APIView):
  permission_classes = [IsAuthenticated]


  @extend_schema(
    request=ChangePasswordSerializer,
    responses={200:None, 400: 'Validation Error'}
  )
  def patch(self, request):
    user = request.user
    serializer = ChangePasswordSerializer(data=request.data)

    if not serializer.is_valid():
      errors = serializer.errors
      field, messages = next(iter(errors.items()))
      readable_field = field.replace('_', ' ').capitalize()
      first_message = messages[0] if isinstance(messages, list) else messages
      error_message = f"{readable_field}: {first_message}"
      return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

    new_password = serializer.validated_data['new_password']

    user.set_password(new_password)
    user.save()

    return Response({'message': 'Password changed successfully.'}, status=200)

@extend_schema(
  request=OpenApiRequest(
    {
      'type': 'object',
      'properties': {
        'current_password': {'type': 'string'},
        'new_password': {'type': 'string'},
      },
      'required': ['current_password', 'new_password']
    }
  ),
  responses={200:None, 400: 'Validation Error'}

)
@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def change_current_password(request):
  user = request.user
  current_password = request.data.get('current_password')
  new_password = request.data.get('new_password')

  if not current_password or not new_password:
    return Response(
      {"error": "Both current_password and new_password are required."},
      status=status.HTTP_400_BAD_REQUEST
    )

  if not user.check_password(current_password):
    return Response(
      {"error": "Current password is incorrect."},
      status=status.HTTP_400_BAD_REQUEST
    )

  user.set_password(new_password)
  user.save()

  return Response({'message': 'Password changed successfully.'}, status=200)

@extend_schema(
  request=ForgetPasswordSerializer,
  responses={200:None, 400: 'Validation Error'}
)
@api_view(['POST'])
@permission_classes([AllowAny])
def forget_password_otp(request):
  serializer = ForgetPasswordSerializer(data=request.data)
  if not serializer.is_valid():
    errors = serializer.errors
    field, messages = next(iter(errors.items()))
    readable_field = field.replace('_', ' ').capitalize()
    first_message = messages[0] if isinstance(messages, list) else messages
    error_message = f"{readable_field}: {first_message}"
    return Response({"error": error_message}, status=400)

  email = serializer.validated_data.get('email')
  phone_number = serializer.validated_data.get('phone_number')

  # Find user by email or phone
  user = None
  if email:
    user = User.objects.filter(email=email, is_active=True).first()
  elif phone_number:
    user = User.objects.filter(phone_number=phone_number, is_active=True).first()

  if not user:
    return Response({'error': 'User not found'}, status=404)

  # Generate OTP and expiry
  otp = random.randint(1000, 9999)
  user.otp = str(otp)
  user.otp_expires = timezone.now() + timedelta(minutes=1)
  user.save(update_fields=['otp', 'otp_expires'])

  # Send OTP via correct channel
  if user.email:
    send_otp_for_password(user.email, otp)
    message = 'OTP sent to email.'
  elif user.phone_number:
    send_otp_for_sms_password(user.phone_number, otp)
    message = 'OTP sent to phone number.'
  else:
    message = 'OTP generated but no delivery method available.'

  return Response({
    'message': message,
    'status': 'success'
  }, status=200)

class LoginView(APIView):
  @extend_schema(
    request=inline_serializer(
      name="LoginPayload",
      fields={
        "email_or_phone": serializers.CharField(),
        "password": serializers.CharField()
      }
    ),
    responses={
      200: inline_serializer(
        name="LoginSuccess",
        fields={
          "message": serializers.CharField(),
          "user": serializers.DictField(),
          "tokens": serializers.DictField(),
        }
      ),
      400: inline_serializer(
        name="LoginError",
        fields={
          "error": serializers.CharField()
        }
      ),
    }
  )
  def post(self, request):
    username = request.data.get("email_or_phone")
    password = request.data.get("password")

    if not username or not password:
      return Response(
        {"error": "email_or_phone and password are required."},
        status=status.HTTP_400_BAD_REQUEST
      )

    user = authenticate(request, username=username, password=password)

    if not user:
      return Response(
        {"error": "Invalid credentials."},
        status=status.HTTP_400_BAD_REQUEST
      )

    if not user.is_active:
      return Response(
        {"error": "Account is not active."},
        status=status.HTTP_400_BAD_REQUEST
      )

    # Generate JWT
    refresh = RefreshToken.for_user(user)

    return Response({
      "message": "Login successful.",
      "user": {
        "id": user.id,
        "email": user.email,
        "phone_number": user.phone_number,
        "full_name": user.full_name,
        "role": 'Customer' if not user.is_staff else 'Vendor'
      },
      "tokens": {
        "refresh": str(refresh),
        "access": str(refresh.access_token)
      }
    })

class LogoutAPIView(APIView):
  permission_classes = [IsAuthenticated]

  @extend_schema(
    request=LogoutSerializer,
    responses={205: None, 400: 'Validation Error'}
  )
  def post(self, request):
    serializer = LogoutSerializer(data=request.data)
    if serializer.is_valid():
      refresh_token = serializer.validated_data['refresh_token']
      try:
        RefreshToken(refresh_token).blacklist()
        return Response({'message': 'Successfully logged out'}, status=status.HTTP_205_RESET_CONTENT)
      except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    errors = serializer.errors
    field, messages = next(iter(errors.items()))
    readable_field = field.replace('_', ' ').capitalize()
    first_message = messages[0] if isinstance(messages, list) else messages
    error_message = f"{readable_field}: {first_message}"
    return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

class CustomerProfileAPIView(APIView):
  permission_classes = [IsCustomer]
  def get(self, request):
    user = request.user

    serializer = CustomerProfileSerializer(user,context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)

  @extend_schema(
    request=CustomerProfileSerializer,
    responses={200: CustomerProfileSerializer, 400: 'Validation Error'}
  )
  def patch(self, request):
    user = request.user
    serializer = CustomerProfileSerializer(user, data=request.data, partial=True, context={'request': request})
    if serializer.is_valid():
      serializer.save()
      return Response(serializer.data, status=status.HTTP_200_OK)
    errors = serializer.errors
    field, messages = next(iter(errors.items()))
    readable_field = field.replace('_', ' ').capitalize()
    first_message = messages[0] if isinstance(messages, list) else messages
    error_message = f"{readable_field}: {first_message}"
    return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

class VendorProfileAPIView(APIView):
  permission_classes = [IsEmployee]

  def get(self, request):
    employee = request.employee  # ← now reliably set
    logger.info(employee)
    laundrymart = employee.laundrymart_store

    serializer = VendorProfileSerializer(
      laundrymart,
      context={'request': request}
    )
    return Response(serializer.data)

  @extend_schema(
    request=VendorProfileSerializer,
    responses={200: VendorProfileSerializer, 400: 'Validation Error'}
  )
  def patch(self, request):
    user = request.user
    laundrymart= user.laundrymart_store
    serializer = VendorProfileSerializer(laundrymart, data=request.data, partial=True, context={'request': request})
    if serializer.is_valid():
      serializer.save()
      return Response(serializer.data, status=status.HTTP_200_OK)
    errors = serializer.errors
    field, messages = next(iter(errors.items()))
    readable_field = field.replace('_', ' ').capitalize()
    first_message = messages[0] if isinstance(messages, list) else messages
    error_message = f"{readable_field}: {first_message}"
    return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_account(request):
  user = request.user
  user.delete()
  return Response({'message': 'Account deleted successfully.'}, status=status.HTTP_200_OK)

class ManageVendorSettingsAPIView(APIView):
  permission_classes = [IsEmployee]

  def get(self, request):
    user = request.employee
    laundrymart= user.laundrymart_store
    serializer = VendorSettingSerializer(laundrymart)
    return Response(serializer.data, status=status.HTTP_200_OK)
  @extend_schema(
    request=VendorSettingSerializer,
    responses={200: VendorSettingSerializer, 400: 'Validation Error'}
  )
  def patch(self, request):
    user = request.user
    laundrymart = user.laundrymart_store
    if user.groups.filter(name='employee_without_edit_permission').exists():
      return Response({"error": "You do not have permission to edit this information"}, status=status.HTTP_403_FORBIDDEN)
    serializer = VendorSettingSerializer(laundrymart, data=request.data, partial=True)
    if serializer.is_valid():
      serializer.save()
      return Response(serializer.data, status=status.HTTP_200_OK)
    errors = serializer.errors
    field, messages = next(iter(errors.items()))
    readable_field = field.replace('_', ' ').capitalize()
    first_message = messages[0] if isinstance(messages, list) else messages
    error_message = f"{readable_field}: {first_message}"
    return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

class ManageCustomerSettingsAPIView(APIView):
  permission_classes = [IsCustomer]

  def get(self, request):
    user = request.user

    serializer = CustomerSettingSerializer(user)
    return Response(serializer.data, status=status.HTTP_200_OK)
  @extend_schema(
    request=CustomerSettingSerializer,
    responses={200: CustomerSettingSerializer, 400: 'Validation Error'}
  )
  def patch(self, request):
    user = request.user
    serializer = CustomerSettingSerializer(user, data=request.data, partial=True)
    if serializer.is_valid():
      serializer.save()
      return Response(serializer.data, status=status.HTTP_200_OK)
    errors = serializer.errors
    field, messages = next(iter(errors.items()))
    readable_field = field.replace('_', ' ').capitalize()
    first_message = messages[0] if isinstance(messages, list) else messages
    error_message = f"{readable_field}: {first_message}"
    return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

class SecondaryLocationAPIView(APIView):
  permission_classes = [IsCustomer]

  @extend_schema(
    request=SecondaryLocationSerializer,
    responses={200: SecondaryLocationSerializer, 400: 'Validation Error'}
  )

  def post(self, request):
    user = request.user
    serializer = SecondaryLocationSerializer(data=request.data)
    if serializer.is_valid():
      serializer.save(user=user)
      return Response({'message':'Location added', 'data':serializer.data}, status=status.HTTP_200_OK)
    errors = serializer.errors
    field, messages = next(iter(errors.items()))
    readable_field = field.replace('_', ' ').capitalize()
    first_message = messages[0] if isinstance(messages, list) else messages
    error_message = f"{readable_field}: {first_message}"
    return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

  def get(self, request):
    user = request.user
    final_result = [{
      'type': 'Home',
      'location': user.location,
      'lat': user.lat,
      'lng': user.lng
    }] if (user.location and user.lat and user.lng) else []
    for loc in user.secondary_locations.all():
      final_result.append({
        'id': loc.id,
        'type': loc.type,
        'location': loc.location,
        'lat': loc.lat,
        'lng': loc.lng
      })
    return Response(final_result)

class SecondaryLocationModifyAPIView(APIView):

  permission_classes=[IsCustomer]

  @extend_schema(
    request=SecondaryLocationSerializer,
    responses={200: SecondaryLocationSerializer, 400: 'Validation Error', 404: 'Not Found'}
  )
  def patch(self, request, pk=None):
    if pk is None:
      # Update primary location
      user = request.user
      user_fields = ['location', 'lat', 'lng']
      for field in user_fields:
        if field in request.data:
          setattr(user, field, request.data[field])
      user.save()
      return Response({
        'type': 'primary',
        'location': user.location,
        'lat': user.lat,
        'lng': user.lng
      }, status=status.HTTP_200_OK)
    else:
      # Update secondary location
      loc = get_object_or_404(SecondaryLocation, pk=pk, user=request.user)
      serializer = SecondaryLocationSerializer(loc,data=request.data, partial=True)
      if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
      return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

  def delete(self, request, pk=None):
    location = get_object_or_404(SecondaryLocation, pk=pk, user=request.user)
    location.delete()
    return Response({'detail': 'Location deleted successfully'}, status=status.HTTP_200_OK)


class EmployeeLoginOTP(APIView):
  permission_classes = [AllowAny]
  @extend_schema(
    request=EmployeeLoginSerializer,
  )
  def post(self, request):
    # Get the employee's username and password from the request
    username = request.data.get('username')
    password = request.data.get('password')
    laundrymart_phone_number=request.data.get('phone_number')

    if not username or not password or not laundrymart_phone_number:
      return Response({"error": "Username and password are required"}, status=status.HTTP_400_BAD_REQUEST)

    # Validate that the employee exists
    laundrymart = LaundrymartStore.objects.get(phone_number=laundrymart_phone_number)
    employee = get_object_or_404(Employee,laundrymart_store=laundrymart, username=username)
    # Check the password
    if not employee.check_password(password):
      return Response({"error": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)

    # Get the admin associated with the LaundrymartStore
    laundrymart_store = employee.laundrymart_store
    admin = laundrymart_store.admin  # Assuming admin is a related field to the LaundrymartStore

    # Generate OTP
    otp = generate_otp()

    # Send OTP to the admin
    send_otp_for_admin_verification(admin, otp)

    return Response({"message": "OTP sent to admin for verification"}, status=status.HTTP_200_OK)

class EmployeeOtpSerializer(serializers.Serializer):
  phone_number=serializers.CharField()
  username = serializers.CharField()
  otp = serializers.CharField()

class VerifyEmployeeOTP(APIView):
  permission_classes = [AllowAny]
  @extend_schema(
    request=EmployeeOtpSerializer,
  )
  @transaction.atomic
  def patch(self, request):
    otp = request.data.get('otp')
    username = request.data.get('username')
    phone_number=request.data.get('phone_number')

    # Validate that OTP and username are provided
    if not otp or not username or not phone_number:
      return Response({"error": "OTP and username and store id are required"}, status=status.HTTP_400_BAD_REQUEST)
    laundrymart_store = get_object_or_404(LaundrymartStore, phone_number=phone_number)
    employee = get_object_or_404(Employee,laundrymart_store=laundrymart_store, username=username)


    admin = laundrymart_store.admin  # Get the admin from the store
    admin_refresh = RefreshToken.for_user(admin)

    # Check if the OTP is correct and not expired
    if admin.otp != otp:
      return Response({"error": "Invalid OTP"}, status=status.HTTP_400_BAD_REQUEST)

    if not admin.otp_expires or admin.otp_expires < timezone.now():
      return Response({"error": "OTP expired"}, status=status.HTTP_400_BAD_REQUEST)

    # Clear OTP after successful verification
    admin.otp = None
    admin.otp_expires = None
    admin.save(update_fields=['otp', 'otp_expires'])

    # Generate JWT tokens (both access and refresh)
    # Generate custom tokens (both access and refresh) for the employee
    refresh_token = EmployeeRefreshToken.for_employee(employee)
    access_token = refresh_token.access_token

    # Return the tokens
    data = {
      "message": "OTP verified successfully",
      "tokens": {
        "refresh": str(refresh_token),
        "access": str(access_token),
        "admin_refresh":str(admin_refresh),
        "admin_access":str(admin_refresh.access_token)
      },
      "user": {
        "laundrymart_admin_id":admin.id,
        "id": employee.id,
        "username": employee.username,
        "email": employee.email,
        "name": employee.name,
        "laundrymart_store": employee.laundrymart_store.id,  # Send laundrymart store ID or name as needed
        "role":"employee"
      }
    }

    return Response(data, status=status.HTTP_200_OK)


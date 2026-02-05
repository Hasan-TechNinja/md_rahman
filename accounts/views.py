import random
from datetime import timedelta

from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response

from rest_framework import serializers, status
from rest_framework_simplejwt.views import TokenObtainPairView

from laundrymart.permissions import IsCustomer, IsStaff
from message_utils.email_utils import send_otp_for_email_verification, send_otp_for_password, \
  send_otp_for_sms_password, send_otp_for_sms_verification
from .models import SecondaryLocation, User
from .serializers import CreateUserSerializer, CustomerProfileSerializer, CustomerSettingSerializer, \
  ForgetPasswordSerializer, LogoutSerializer, \
  OTPSerializer, \
  ResendOTPSerializer, \
  ChangePasswordSerializer, SecondaryLocationSerializer, VendorProfileSerializer, VendorSettingSerializer
from drf_spectacular.utils import OpenApiExample, OpenApiRequest, extend_schema, OpenApiResponse, inline_serializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated, AllowAny


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
    print(email, phone_number)

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
    print(existing_user)

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
      print({"error": f"{readable_field}: {first_message}"})
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

    # Activate and verify user
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
        "access": str(refresh.access_token)
      }
    }

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
  permission_classes = [IsStaff]

  def get(self, request):
    user = request.user
    laundrymart= user.laundrymart_store
    serializer = VendorProfileSerializer(laundrymart, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)

  @extend_schema(
    request=VendorProfileSerializer,
    responses={200: VendorProfileSerializer, 400: 'Validation Error'}
  )
  def patch(self, request):
    user = request.user
    laundrymart= user.laundrymart_store
    if user.groups.filter(name='employee_without_edit_permission').exists():
      return Response({"error": "You do not have permission to edit this information"}, status=status.HTTP_403_FORBIDDEN)
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
  permission_classes = [IsStaff]

  def get(self, request):
    user = request.user
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

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    firstName = serializers.CharField(source='first_name', required=False, allow_blank=True)
    lastName = serializers.CharField(source='last_name', required=False, allow_blank=True)
    preferredLanguage = serializers.ChoiceField(source='preferred_language', choices=User.Language.choices, required=False)
    dateJoined = serializers.DateTimeField(source='date_joined', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'firstName', 'lastName', 'phone', 'role', 'preferredLanguage', 'dateJoined']
        read_only_fields = ['id', 'email', 'role', 'dateJoined']


class RegisterSerializer(serializers.ModelSerializer):
    firstName = serializers.CharField(source='first_name', max_length=150)
    lastName = serializers.CharField(source='last_name', max_length=150, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    # Hotel owners can sign up themselves (their listings still need admin approval); admins can't
    accountType = serializers.ChoiceField(source='role', choices=[('traveler', 'Traveler'), ('owner', 'Hotel owner')],
                                          default='traveler', write_only=True)

    class Meta:
        model = User
        fields = ['email', 'password', 'firstName', 'lastName', 'phone', 'accountType']

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value.lower()

    def validate(self, attrs):
        validate_password(attrs['password'], user=User(email=attrs['email'], first_name=attrs.get('first_name', '')))
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """JWT login that also returns the user profile."""

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = UserSerializer(self.user).data
        return data

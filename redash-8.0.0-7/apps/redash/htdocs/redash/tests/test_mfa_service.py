"""
Unit tests for MFA Service.

Tests the Multi-Factor Authentication service including:
- MFA requirement checking for different roles
- OTP generation and verification
- Rate limiting logic
- Account lockout after failed attempts
- Backup code generation and verification
- Phone number validation
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from redash.models import db, User, Group, MFAConfig, MFABackupCode
from redash.services.mfa_service import MFAService


class TestMFARequirementChecking:
    """Test MFA requirement checking for different roles."""
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user."""
        user = Mock(spec=User)
        user.id = 1
        user.email = 'test@example.com'
        user.group_ids = []
        return user
    
    def test_mfa_required_for_org_admin(self, mock_user):
        """
        Test that MFA is required for Organization Admin role.
        
        Requirements: 2.1
        """
        mock_user.group_ids = [1, 2]
        
        mock_group_admin = Mock(spec=Group)
        mock_group_admin.role_type = Group.ROLE_ORG_ADMIN
        
        mock_group_default = Mock(spec=Group)
        mock_group_default.role_type = Group.ROLE_DEFAULT
        
        with patch.object(Group.query, 'filter') as mock_filter:
            mock_filter.return_value.all.return_value = [mock_group_admin, mock_group_default]
            
            result = MFAService.is_mfa_required(mock_user)
            
            assert result == True
    
    def test_mfa_required_for_super_admin(self, mock_user):
        """
        Test that MFA is required for Super Admin role.
        
        Requirements: 2.1
        """
        mock_user.group_ids = [3]
        
        mock_group = Mock(spec=Group)
        mock_group.role_type = Group.ROLE_SUPER_ADMIN
        
        with patch.object(Group.query, 'filter') as mock_filter:
            mock_filter.return_value.all.return_value = [mock_group]
            
            result = MFAService.is_mfa_required(mock_user)
            
            assert result == True
    
    def test_mfa_not_required_for_default_role(self, mock_user):
        """
        Test that MFA is not required for Default role.
        
        Requirements: 2.1
        """
        mock_user.group_ids = [1]
        
        mock_group = Mock(spec=Group)
        mock_group.role_type = Group.ROLE_DEFAULT
        
        with patch.object(Group.query, 'filter') as mock_filter:
            mock_filter.return_value.all.return_value = [mock_group]
            
            result = MFAService.is_mfa_required(mock_user)
            
            assert result == False
    
    def test_mfa_not_required_for_designer_role(self, mock_user):
        """
        Test that MFA is not required for Designer role.
        
        Requirements: 2.1
        """
        mock_user.group_ids = [2]
        
        mock_group = Mock(spec=Group)
        mock_group.role_type = Group.ROLE_DESIGNER
        
        with patch.object(Group.query, 'filter') as mock_filter:
            mock_filter.return_value.all.return_value = [mock_group]
            
            result = MFAService.is_mfa_required(mock_user)
            
            assert result == False
    
    def test_mfa_not_required_for_project_owner(self, mock_user):
        """
        Test that MFA is not required for Project Owner role.
        
        Requirements: 2.1
        """
        mock_user.group_ids = [3]
        
        mock_group = Mock(spec=Group)
        mock_group.role_type = Group.ROLE_PROJECT_OWNER
        
        with patch.object(Group.query, 'filter') as mock_filter:
            mock_filter.return_value.all.return_value = [mock_group]
            
            result = MFAService.is_mfa_required(mock_user)
            
            assert result == False
    
    def test_mfa_not_required_for_project_admin(self, mock_user):
        """
        Test that MFA is not required for Project Admin role.
        
        Requirements: 2.1
        """
        mock_user.group_ids = [4]
        
        mock_group = Mock(spec=Group)
        mock_group.role_type = Group.ROLE_PROJECT_ADMIN
        
        with patch.object(Group.query, 'filter') as mock_filter:
            mock_filter.return_value.all.return_value = [mock_group]
            
            result = MFAService.is_mfa_required(mock_user)
            
            assert result == False
    
    def test_mfa_required_with_multiple_roles(self, mock_user):
        """
        Test MFA requirement when user has multiple roles including privileged.
        
        Requirements: 2.1
        """
        mock_user.group_ids = [1, 2, 3]
        
        mock_groups = [
            Mock(spec=Group, role_type=Group.ROLE_DEFAULT),
            Mock(spec=Group, role_type=Group.ROLE_DESIGNER),
            Mock(spec=Group, role_type=Group.ROLE_ORG_ADMIN)
        ]
        
        with patch.object(Group.query, 'filter') as mock_filter:
            mock_filter.return_value.all.return_value = mock_groups
            
            result = MFAService.is_mfa_required(mock_user)
            
            assert result == True


class TestOTPGeneration:
    """Test OTP generation."""
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user."""
        user = Mock(spec=User)
        user.id = 1
        user.email = 'test@example.com'
        return user
    
    @pytest.fixture
    def mock_redis(self):
        """Mock Redis connection."""
        with patch('redash.services.mfa_service.redis_connection') as mock:
            yield mock
    
    def test_generate_otp_success(self, mock_user, mock_redis):
        """
        Test successful OTP generation.
        
        Requirements: 2.6
        """
        mock_redis.get.return_value = None
        
        otp = MFAService.generate_otp(mock_user)
        
        assert len(otp) == 6
        assert otp.isdigit()
        
        # Verify OTP stored in Redis
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == 'mfa:otp:1'
        assert call_args[0][1] == 600  # 10 minutes
        assert call_args[0][2] == otp
    
    def test_generate_otp_resets_attempt_counter(self, mock_user, mock_redis):
        """
        Test that generating OTP resets failed attempt counter.
        
        Requirements: 2.6, 7.6
        """
        mock_redis.get.return_value = None
        
        MFAService.generate_otp(mock_user)
        
        # Verify attempt counter was deleted
        mock_redis.delete.assert_called_with('mfa:attempts:1')
    
    def test_generate_otp_increments_sms_counter(self, mock_user, mock_redis):
        """
        Test that generating OTP increments SMS request counter.
        
        Requirements: 2.6, 7.1
        """
        mock_redis.get.return_value = None
        mock_redis.incr.return_value = 1
        
        MFAService.generate_otp(mock_user)
        
        # Verify SMS counter was incremented
        mock_redis.incr.assert_called_with('mfa:sms_requests:1')
        mock_redis.expire.assert_called_with('mfa:sms_requests:1', 600)
    
    def test_generate_otp_rate_limit_exceeded(self, mock_user, mock_redis):
        """
        Test OTP generation fails when rate limit exceeded.
        
        Requirements: 7.1
        """
        # Simulate 3 SMS requests already sent
        mock_redis.get.return_value = b'3'
        
        with pytest.raises(Exception) as exc_info:
            MFAService.generate_otp(mock_user)
        
        assert 'Too many SMS requests' in str(exc_info.value)
    
    def test_generate_otp_within_rate_limit(self, mock_user, mock_redis):
        """
        Test OTP generation succeeds within rate limit.
        
        Requirements: 7.1
        """
        # Simulate 2 SMS requests already sent (under limit of 3)
        mock_redis.get.return_value = b'2'
        mock_redis.incr.return_value = 3
        
        otp = MFAService.generate_otp(mock_user)
        
        assert len(otp) == 6
        assert otp.isdigit()


class TestOTPVerification:
    """Test OTP verification."""
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user."""
        user = Mock(spec=User)
        user.id = 1
        user.email = 'test@example.com'
        return user
    
    @pytest.fixture
    def mock_redis(self):
        """Mock Redis connection."""
        with patch('redash.services.mfa_service.redis_connection') as mock:
            yield mock
    
    @pytest.fixture
    def mock_config(self):
        """Mock MFA config."""
        config = Mock(spec=MFAConfig)
        config.user_id = 1
        return config
    
    def test_verify_otp_success(self, mock_user, mock_redis, mock_config):
        """
        Test successful OTP verification.
        
        Requirements: 2.6
        """
        mock_redis.get.side_effect = [
            None,  # No lock
            b'123456'  # Stored OTP
        ]
        
        with patch.object(MFAConfig.query, 'filter_by') as mock_filter, \
             patch.object(db.session, 'commit'):
            mock_filter.return_value.first.return_value = mock_config
            
            result = MFAService.verify_otp(mock_user, '123456')
            
            assert result == True
            mock_redis.delete.assert_any_call('mfa:otp:1')
            mock_redis.delete.assert_any_call('mfa:attempts:1')
            mock_config.mark_used.assert_called_once()
    
    def test_verify_otp_invalid_code(self, mock_user, mock_redis):
        """
        Test OTP verification with invalid code.
        
        Requirements: 2.6, 7.6
        """
        mock_redis.get.side_effect = [
            None,  # No lock
            b'123456',  # Stored OTP
            None  # Attempt counter
        ]
        
        with pytest.raises(Exception) as exc_info:
            MFAService.verify_otp(mock_user, '999999')
        
        assert 'Invalid OTP' in str(exc_info.value)
        assert '4 attempts remaining' in str(exc_info.value)
        
        # Verify attempt counter was incremented
        mock_redis.incr.assert_called_with('mfa:attempts:1')
    
    def test_verify_otp_expired(self, mock_user, mock_redis):
        """
        Test OTP verification when OTP has expired.
        
        Requirements: 2.6
        """
        mock_redis.get.side_effect = [
            None,  # No lock
            None  # No stored OTP (expired)
        ]
        
        with pytest.raises(Exception) as exc_info:
            MFAService.verify_otp(mock_user, '123456')
        
        assert 'OTP expired or not found' in str(exc_info.value)
    
    def test_verify_otp_account_locked(self, mock_user, mock_redis):
        """
        Test OTP verification when account is locked.
        
        Requirements: 7.6
        """
        # Simulate 5 failed attempts (account locked)
        mock_redis.get.side_effect = [
            b'5',  # Failed attempts
            None  # TTL check
        ]
        mock_redis.ttl.return_value = 600  # 10 minutes remaining
        
        with pytest.raises(Exception) as exc_info:
            MFAService.verify_otp(mock_user, '123456')
        
        assert 'Account locked' in str(exc_info.value)
        assert '10 minutes' in str(exc_info.value)
    
    def test_verify_otp_locks_after_max_attempts(self, mock_user, mock_redis):
        """
        Test account locks after maximum failed attempts.
        
        Requirements: 7.6
        """
        mock_redis.get.side_effect = [
            None,  # No lock initially
            b'123456',  # Stored OTP
            b'4'  # 4 previous failed attempts
        ]
        mock_redis.incr.return_value = 5
        
        with pytest.raises(Exception) as exc_info:
            MFAService.verify_otp(mock_user, '999999')
        
        assert 'Too many failed attempts' in str(exc_info.value)
        assert 'locked for 15 minutes' in str(exc_info.value)
        
        # Verify account was locked
        mock_redis.setex.assert_called_with('mfa:locked:1', 900, '1')


class TestRateLimiting:
    """Test rate limiting logic."""
    
    @pytest.fixture
    def mock_redis(self):
        """Mock Redis connection."""
        with patch('redash.services.mfa_service.redis_connection') as mock:
            yield mock
    
    def test_rate_limit_check_within_limit(self, mock_redis):
        """
        Test rate limit check when within limit.
        
        Requirements: 7.1
        """
        mock_redis.get.return_value = b'2'
        
        result = MFAService._check_sms_rate_limit(1)
        
        assert result == True
    
    def test_rate_limit_check_at_limit(self, mock_redis):
        """
        Test rate limit check when at limit.
        
        Requirements: 7.1
        """
        mock_redis.get.return_value = b'3'
        
        result = MFAService._check_sms_rate_limit(1)
        
        assert result == False
    
    def test_rate_limit_check_exceeded(self, mock_redis):
        """
        Test rate limit check when exceeded.
        
        Requirements: 7.1
        """
        mock_redis.get.return_value = b'5'
        
        result = MFAService._check_sms_rate_limit(1)
        
        assert result == False
    
    def test_rate_limit_check_no_requests(self, mock_redis):
        """
        Test rate limit check with no previous requests.
        
        Requirements: 7.1
        """
        mock_redis.get.return_value = None
        
        result = MFAService._check_sms_rate_limit(1)
        
        assert result == True
    
    def test_increment_sms_counter_first_request(self, mock_redis):
        """
        Test incrementing SMS counter on first request sets expiry.
        
        Requirements: 7.1
        """
        mock_redis.incr.return_value = 1
        
        MFAService._increment_sms_request_counter(1)
        
        mock_redis.incr.assert_called_with('mfa:sms_requests:1')
        mock_redis.expire.assert_called_with('mfa:sms_requests:1', 600)
    
    def test_increment_sms_counter_subsequent_request(self, mock_redis):
        """
        Test incrementing SMS counter on subsequent request.
        
        Requirements: 7.1
        """
        mock_redis.incr.return_value = 2
        
        MFAService._increment_sms_request_counter(1)
        
        mock_redis.incr.assert_called_with('mfa:sms_requests:1')
        # Expire should not be called for subsequent requests
        mock_redis.expire.assert_not_called()


class TestAccountLockout:
    """Test account lockout after failed attempts."""
    
    @pytest.fixture
    def mock_redis(self):
        """Mock Redis connection."""
        with patch('redash.services.mfa_service.redis_connection') as mock:
            yield mock
    
    def test_increment_failed_attempts(self, mock_redis):
        """
        Test incrementing failed attempt counter.
        
        Requirements: 7.6
        """
        MFAService._increment_failed_attempts(1)
        
        mock_redis.incr.assert_called_with('mfa:attempts:1')
        mock_redis.expire.assert_called_with('mfa:attempts:1', 900)
    
    def test_get_failed_attempts_with_attempts(self, mock_redis):
        """
        Test getting failed attempt count.
        
        Requirements: 7.6
        """
        mock_redis.get.return_value = b'3'
        
        count = MFAService._get_failed_attempts(1)
        
        assert count == 3
    
    def test_get_failed_attempts_no_attempts(self, mock_redis):
        """
        Test getting failed attempt count when none exist.
        
        Requirements: 7.6
        """
        mock_redis.get.return_value = None
        
        count = MFAService._get_failed_attempts(1)
        
        assert count == 0
    
    def test_is_account_locked_true(self, mock_redis):
        """
        Test checking if account is locked when it is.
        
        Requirements: 7.6
        """
        mock_redis.get.return_value = b'5'
        
        result = MFAService._is_account_locked(1)
        
        assert result == True
    
    def test_is_account_locked_false(self, mock_redis):
        """
        Test checking if account is locked when it is not.
        
        Requirements: 7.6
        """
        mock_redis.get.return_value = b'3'
        
        result = MFAService._is_account_locked(1)
        
        assert result == False
    
    def test_lock_account(self, mock_redis):
        """
        Test locking an account.
        
        Requirements: 7.6
        """
        MFAService._lock_account(1)
        
        mock_redis.setex.assert_called_with('mfa:locked:1', 900, '1')
    
    def test_get_lockout_remaining_with_time(self, mock_redis):
        """
        Test getting remaining lockout time.
        
        Requirements: 7.6
        """
        mock_redis.ttl.return_value = 600  # 10 minutes in seconds
        
        remaining = MFAService._get_lockout_remaining(1)
        
        assert remaining == 10
    
    def test_get_lockout_remaining_expired(self, mock_redis):
        """
        Test getting remaining lockout time when expired.
        
        Requirements: 7.6
        """
        mock_redis.ttl.return_value = -1  # Key doesn't exist
        
        remaining = MFAService._get_lockout_remaining(1)
        
        assert remaining == 0


class TestBackupCodeGeneration:
    """Test backup code generation."""
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user."""
        user = Mock(spec=User)
        user.id = 1
        user.email = 'test@example.com'
        return user
    
    def test_generate_backup_codes(self, mock_user):
        """
        Test generating backup codes for a user.
        
        Requirements: 2.6
        """
        with patch.object(MFABackupCode, 'generate_codes_for_user') as mock_generate, \
             patch.object(db.session, 'commit'):
            mock_generate.return_value = ['CODE1234', 'CODE5678', 'CODE9ABC']
            
            codes = MFAService._generate_backup_codes(mock_user)
            
            assert len(codes) == 3
            assert 'CODE1234' in codes
            mock_generate.assert_called_once_with(1, count=10)
    
    def test_regenerate_backup_codes(self, mock_user):
        """
        Test regenerating backup codes invalidates old ones.
        
        Requirements: 2.6
        """
        with patch.object(MFABackupCode, 'invalidate_all') as mock_invalidate, \
             patch.object(MFABackupCode, 'generate_codes_for_user') as mock_generate, \
             patch.object(db.session, 'commit'):
            mock_generate.return_value = ['NEW1234', 'NEW5678']
            
            codes = MFAService.regenerate_backup_codes(mock_user)
            
            mock_invalidate.assert_called_once_with(1)
            assert len(codes) == 2
            assert 'NEW1234' in codes


class TestBackupCodeVerification:
    """Test backup code verification."""
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user."""
        user = Mock(spec=User)
        user.id = 1
        user.email = 'test@example.com'
        return user
    
    @pytest.fixture
    def mock_config(self):
        """Mock MFA config."""
        config = Mock(spec=MFAConfig)
        config.user_id = 1
        return config
    
    def test_verify_backup_code_success(self, mock_user, mock_config):
        """
        Test successful backup code verification.
        
        Requirements: 2.6
        """
        with patch.object(MFABackupCode, 'verify_and_use') as mock_verify, \
             patch.object(MFAConfig.query, 'filter_by') as mock_filter, \
             patch.object(db.session, 'commit'):
            mock_verify.return_value = (True, 7)
            mock_filter.return_value.first.return_value = mock_config
            
            success, remaining = MFAService.verify_backup_code(mock_user, 'CODE1234')
            
            assert success == True
            assert remaining == 7
            mock_verify.assert_called_once_with(1, 'CODE1234')
            mock_config.mark_used.assert_called_once()
    
    def test_verify_backup_code_invalid(self, mock_user):
        """
        Test backup code verification with invalid code.
        
        Requirements: 2.6
        """
        with patch.object(MFABackupCode, 'verify_and_use') as mock_verify:
            mock_verify.return_value = (False, None)
            
            success, remaining = MFAService.verify_backup_code(mock_user, 'INVALID')
            
            assert success == False
            assert remaining is None
    
    def test_verify_backup_code_already_used(self, mock_user):
        """
        Test backup code verification with already used code.
        
        Requirements: 2.6
        """
        with patch.object(MFABackupCode, 'verify_and_use') as mock_verify:
            mock_verify.return_value = (False, None)
            
            success, remaining = MFAService.verify_backup_code(mock_user, 'USED1234')
            
            assert success == False
            assert remaining is None


class TestPhoneNumberValidation:
    """Test phone number validation."""
    
    def test_validate_phone_number_valid_us(self):
        """
        Test validation of valid US phone number.
        
        Requirements: 7.6
        """
        result = MFAService._validate_phone_number('+12345678901')
        
        assert result == True
    
    def test_validate_phone_number_valid_international(self):
        """
        Test validation of valid international phone number.
        
        Requirements: 7.6
        """
        result = MFAService._validate_phone_number('+447911123456')
        
        assert result == True
    
    def test_validate_phone_number_invalid_no_plus(self):
        """
        Test validation fails without plus sign.
        
        Requirements: 7.6
        """
        result = MFAService._validate_phone_number('12345678901')
        
        assert result == False
    
    def test_validate_phone_number_invalid_starts_with_zero(self):
        """
        Test validation fails when starting with zero.
        
        Requirements: 7.6
        """
        result = MFAService._validate_phone_number('+01234567890')
        
        assert result == False
    
    def test_validate_phone_number_invalid_too_short(self):
        """
        Test validation fails when too short.
        
        Requirements: 7.6
        """
        result = MFAService._validate_phone_number('+123')
        
        assert result == False
    
    def test_validate_phone_number_invalid_too_long(self):
        """
        Test validation fails when too long.
        
        Requirements: 7.6
        """
        result = MFAService._validate_phone_number('+123456789012345678')
        
        assert result == False
    
    def test_validate_phone_number_invalid_contains_letters(self):
        """
        Test validation fails with letters.
        
        Requirements: 7.6
        """
        result = MFAService._validate_phone_number('+1234567ABC')
        
        assert result == False
    
    def test_validate_phone_number_invalid_empty(self):
        """
        Test validation fails with empty string.
        
        Requirements: 7.6
        """
        result = MFAService._validate_phone_number('')
        
        assert result == False

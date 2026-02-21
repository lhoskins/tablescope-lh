# redash/models/role_assignment.py

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy_utils.models import generic_repr
from six import python_2_unicode_compatible

from redash.models.base import db


@python_2_unicode_compatible
@generic_repr('id', 'user_id', 'role_type', 'resource_type', 'resource_id', 'org_id')
class RoleAssignment(db.Model):
    """
    Model for tracking role assignments to users.
    
    Supports both global roles (e.g., organization_admin, super_admin) and
    resource-specific roles (e.g., project_owner for a specific project).
    """
    __tablename__ = 'role_assignments'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    role_type = Column(String(50), nullable=False)
    resource_type = Column(String(50), nullable=True)  # 'project', 'organization', or NULL for global
    resource_id = Column(Integer, nullable=True)
    org_id = Column(Integer, ForeignKey('organizations.id'), nullable=False)
    assigned_at = Column(DateTime, default=db.func.now())
    assigned_by_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    
    # Relationships
    user = relationship('User', foreign_keys=[user_id], backref='role_assignments')
    assigned_by = relationship('User', foreign_keys=[assigned_by_id])
    organization = relationship('Organization')
    
    # Unique constraint to prevent duplicate role assignments
    __table_args__ = (
        UniqueConstraint('user_id', 'role_type', 'resource_type', 'resource_id', 
                        name='uq_role_assignment'),
    )
    
    def __str__(self):
        if self.resource_type and self.resource_id:
            return u'RoleAssignment({}, {}, {}:{})'.format(
                self.user_id, self.role_type, self.resource_type, self.resource_id
            )
        return u'RoleAssignment({}, {})'.format(self.user_id, self.role_type)
    
    def to_dict(self):
        """
        Convert role assignment to dictionary.
        
        Returns:
            dict: Role assignment data
        """
        return {
            'id': self.id,
            'user_id': self.user_id,
            'role_type': self.role_type,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'org_id': self.org_id,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'assigned_by_id': self.assigned_by_id
        }
    
    @classmethod
    def get_user_roles(cls, user_id, org_id=None):
        """
        Get all role assignments for a user.
        
        Args:
            user_id (int): User ID
            org_id (int, optional): Organization ID to filter by
            
        Returns:
            list: List of RoleAssignment objects
        """
        query = cls.query.filter(cls.user_id == user_id)
        if org_id:
            query = query.filter(cls.org_id == org_id)
        return query.all()
    
    @classmethod
    def get_role_for_resource(cls, user_id, resource_type, resource_id):
        """
        Get role assignment for a specific resource.
        
        Args:
            user_id (int): User ID
            resource_type (str): Resource type (e.g., 'project')
            resource_id (int): Resource ID
            
        Returns:
            RoleAssignment: Role assignment or None
        """
        return cls.query.filter(
            cls.user_id == user_id,
            cls.resource_type == resource_type,
            cls.resource_id == resource_id
        ).first()
    
    @classmethod
    def has_role(cls, user_id, role_type, resource_type=None, resource_id=None):
        """
        Check if user has a specific role.
        
        Args:
            user_id (int): User ID
            role_type (str): Role type to check
            resource_type (str, optional): Resource type
            resource_id (int, optional): Resource ID
            
        Returns:
            bool: True if user has the role
        """
        query = cls.query.filter(
            cls.user_id == user_id,
            cls.role_type == role_type
        )
        
        if resource_type:
            query = query.filter(cls.resource_type == resource_type)
        if resource_id:
            query = query.filter(cls.resource_id == resource_id)
        
        return query.count() > 0
    
    @classmethod
    def assign_role(cls, user_id, role_type, org_id, resource_type=None, 
                   resource_id=None, assigned_by_id=None):
        """
        Assign a role to a user.
        
        Args:
            user_id (int): User ID
            role_type (str): Role type
            org_id (int): Organization ID
            resource_type (str, optional): Resource type
            resource_id (int, optional): Resource ID
            assigned_by_id (int, optional): ID of user making the assignment
            
        Returns:
            RoleAssignment: Created or existing role assignment
        """
        # Check if assignment already exists
        existing = cls.query.filter(
            cls.user_id == user_id,
            cls.role_type == role_type,
            cls.resource_type == resource_type,
            cls.resource_id == resource_id
        ).first()
        
        if existing:
            return existing
        
        # Create new assignment
        assignment = cls(
            user_id=user_id,
            role_type=role_type,
            resource_type=resource_type,
            resource_id=resource_id,
            org_id=org_id,
            assigned_by_id=assigned_by_id
        )
        db.session.add(assignment)
        return assignment
    
    @classmethod
    def revoke_role(cls, user_id, role_type, resource_type=None, resource_id=None):
        """
        Revoke a role from a user.
        
        Args:
            user_id (int): User ID
            role_type (str): Role type
            resource_type (str, optional): Resource type
            resource_id (int, optional): Resource ID
            
        Returns:
            int: Number of assignments deleted
        """
        query = cls.query.filter(
            cls.user_id == user_id,
            cls.role_type == role_type
        )
        
        if resource_type:
            query = query.filter(cls.resource_type == resource_type)
        if resource_id:
            query = query.filter(cls.resource_id == resource_id)
        
        count = query.delete()
        db.session.commit()
        return count
    
    @classmethod
    def get_users_with_role(cls, role_type, org_id, resource_type=None, resource_id=None):
        """
        Get all users with a specific role.
        
        Args:
            role_type (str): Role type
            org_id (int): Organization ID
            resource_type (str, optional): Resource type
            resource_id (int, optional): Resource ID
            
        Returns:
            list: List of user IDs
        """
        query = cls.query.filter(
            cls.role_type == role_type,
            cls.org_id == org_id
        )
        
        if resource_type:
            query = query.filter(cls.resource_type == resource_type)
        if resource_id:
            query = query.filter(cls.resource_id == resource_id)
        
        return [assignment.user_id for assignment in query.all()]

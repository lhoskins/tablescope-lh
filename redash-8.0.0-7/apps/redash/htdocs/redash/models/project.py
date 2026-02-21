# redash/models/projects.py

from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship, backref
from redash.models.base import db
from redash.models.users import User
from redash.models.organizations import Organization

class Project(db.Model):
    __tablename__ = 'projects'

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey('organizations.id'))
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=db.func.now())
    updated_at = Column(DateTime, default=db.func.now(), onupdate=db.func.now())
    owner_id = Column(Integer, ForeignKey('users.id'))
    is_shared = Column(db.Boolean, default=False, nullable=False, index=True)

    # Relationships
    organization = relationship('Organization', back_populates='projects')
    owner = relationship('User', back_populates='owned_projects')
    members = relationship('ProjectMember', back_populates='project', cascade='all, delete-orphan')
    data_sources = relationship('ProjectDataSource', back_populates='project', cascade='all, delete-orphan')

    # Add relationship with DataSourceApproval
    data_source_approvals = relationship('DataSourceApproval', back_populates='project')

    @classmethod
    def get_by_id_and_org(cls, project_id, org):
        """Get a project by ID and organization."""
        return cls.query.filter(cls.id == project_id, cls.org_id == org.id).first()

    def get_migration_status(self):
        """
        Get the current migration status for this project.
        
        Returns:
            dict: Migration status information including:
                - status: 'none', 'in_progress', 'completed', 'failed'
                - migration_type: 'share' or 'unshare' (if applicable)
                - started_at: timestamp when migration started
                - completed_at: timestamp when migration completed
                - error_message: error message if migration failed
                - datasources_migrated: count of datasources migrated
                - queries_migrated: count of queries migrated
        """
        from redash.models.data_migration_log import DataMigrationLog
        
        # Get the most recent migration log for this project
        latest_migration = DataMigrationLog.query.filter_by(
            project_id=self.id
        ).order_by(DataMigrationLog.started_at.desc()).first()
        
        if not latest_migration:
            return {
                'status': 'none',
                'migration_type': None,
                'started_at': None,
                'completed_at': None,
                'error_message': None,
                'datasources_migrated': 0,
                'queries_migrated': 0
            }
        
        return {
            'status': latest_migration.status,
            'migration_type': latest_migration.migration_type,
            'started_at': latest_migration.started_at.isoformat() if latest_migration.started_at else None,
            'completed_at': latest_migration.completed_at.isoformat() if latest_migration.completed_at else None,
            'error_message': latest_migration.error_message,
            'datasources_migrated': latest_migration.datasources_migrated,
            'queries_migrated': latest_migration.queries_migrated
        }

    def to_dict(self, include_migration_status=False):
        """
        Convert project to dictionary.
        
        Args:
            include_migration_status: If True, include migration status in response
        
        Returns:
            dict: Project data
        """
        result = {
            'id': self.id,
            'org_id': self.org_id,
            'name': self.name,
            'description': self.description,
            'type': self.type,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'owner_id': self.owner_id,
            'is_shared': self.is_shared,
            'members': [member.to_dict() for member in self.members] if self.members else [],
            'data_sources': [ds.to_dict() for ds in self.data_sources] if self.data_sources else [],
        }
        
        if include_migration_status:
            result['migration_status'] = self.get_migration_status()
        
        return result

class ProjectMember(db.Model):
    __tablename__ = "project_members"

    project_id = Column(Integer, ForeignKey("projects.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    
    # RBAC fields
    role = Column(String(50), default='member')  # 'owner', 'admin', or 'member'
    added_at = Column(DateTime, default=db.func.now())
    added_by_id = Column(Integer, ForeignKey('users.id'), nullable=True)

    # Relationships
    project = relationship("Project", back_populates="members")
    user = relationship("User", backref="project_memberships", foreign_keys=[user_id])
    added_by = relationship("User", foreign_keys=[added_by_id], backref="added_members")

    def can_manage_project(self):
        """
        Check if this member can manage the project.
        
        Returns:
            bool: True if member has owner or admin role
        """
        return self.role in ['owner', 'admin']
    
    def can_delete_project(self):
        """
        Check if this member can delete the project.
        Only project owners can delete projects.
        
        Returns:
            bool: True if member has owner role
        """
        return self.role == 'owner'

    def to_dict(self):
        return {
            "project_id": self.project_id,
            "user_id": self.user_id,
            "role": self.role,
            "added_at": self.added_at.isoformat() if self.added_at else None,
            "added_by_id": self.added_by_id,
        }


class ProjectDataSource(db.Model):
    __tablename__ = 'project_data_sources'

    project_id = Column(Integer, ForeignKey('projects.id'), primary_key=True)
    data_source_id = Column(Integer, ForeignKey('data_sources.id'), primary_key=True)
    owner = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Relationships
    project = relationship('Project', back_populates='data_sources')
    data_source = relationship('DataSource', backref='project_data_sources')  # Assuming DataSource model exists
    owner_user = relationship('User', backref='owned_project_data_sources')  # Linking to the User model

    def to_dict(self):
        return {
            'project_id': self.project_id,
            'data_source_id': self.data_source_id,
            'owner': self.owner,
            'data_source': self.data_source.to_dict() if self.data_source else None,
        }

    __tablename__ = 'project_data_sources'

    project_id = Column(Integer, ForeignKey('projects.id'), primary_key=True)
    data_source_id = Column(Integer, ForeignKey('data_sources.id'), primary_key=True)
    owner = Column(Integer, ForeignKey('users.id'), nullable=False)

    project = relationship('Project', back_populates='data_sources')
    data_source = relationship('DataSource')  # Assuming DataSource model exists

    def to_dict(self):
        return {
            'project_id': self.project_id,
            'data_source_id': self.data_source_id,
            'owner': self.owner,
            'data_source': self.data_source.to_dict() if self.data_source else None,
        }
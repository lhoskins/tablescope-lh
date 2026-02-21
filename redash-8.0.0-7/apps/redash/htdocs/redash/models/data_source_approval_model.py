from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from redash.models.base import db


class DataSourceApproval(db.Model):
    __tablename__ = "data_source_approval"

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    group_name = Column(String(255), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    group_owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    project_owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    project_name = Column(String(255), nullable=True)
    datasource_id = Column(Integer, ForeignKey("data_sources.id"), nullable=False)
    data_source_owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    approval_type = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="Pending")
    comments = Column(Text, nullable=True)

    # Audit Fields
    created_date = Column(DateTime, default=db.func.now())
    approved_date = Column(DateTime, nullable=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    requester_name = Column(String(255), nullable=False)
    requester_email = Column(String(255), nullable=False)
    approver_name = Column(String(255), nullable=True)
    approver_email = Column(String(255), nullable=True)

    # Relationships
    group = relationship("Group", back_populates="data_source_approvals")
    project = relationship("Project", back_populates="data_source_approvals")
    data_source = relationship("DataSource", back_populates="data_source_approvals")
    data_source_owner = relationship("User", foreign_keys=[data_source_owner_id])
    requester = relationship("User", foreign_keys=[requester_id])

    def to_dict(self):
        return {
            "id": self.id,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "datasource_id": self.datasource_id,
            "data_source_owner_id": self.data_source_owner_id,
            "approval_type": self.approval_type,
            "status": self.status,
            "comments": self.comments,
            "created_date": self.created_date,
            "approved_date": self.approved_date,
            "requester_id": self.requester_id,
            "requester_name": self.requester_name,
            "requester_email": self.requester_email,
            "approver_name": self.approver_name,
            "approver_email": self.approver_email,
            "data_source_name": self.data_source.name if self.data_source else None,
            "data_source_owner_name": self.data_source_owner.name if self.data_source_owner else "N/A",
        }

    @classmethod
    def create(cls, datasource_id, approval_type, requester_id, owner_id, project_id=None, group_id=None):
        group_name = None
        project_name = None
        requester = models.User.query.get(requester_id)

        if group_id:
            group = models.Group.query.get(group_id)
            group_name = group.name if group else None

        if project_id:
            project = models.Project.query.get(project_id)
            project_name = project.name if project else None

        new_approval = cls(
            datasource_id=datasource_id,
            approval_type=approval_type,
            status="Pending",
            project_id=project_id if approval_type == "Project" else None,
            group_id=group_id if approval_type == "Group" else None,
            project_owner_id=owner_id if approval_type == "Project" else None,
            group_owner_id=owner_id if approval_type == "Group" else None,
            group_name=group_name,
            project_name=project_name,
            requester_id=requester_id,
            requester_name=requester.name if requester else None,
            requester_email=requester.email if requester else None,
        )
        db.session.add(new_approval)
        db.session.commit()
        return new_approval

    @staticmethod
    def update_status(approval_id, new_status, approver_id):
        """
        Update the status of a DataSourceApproval and populate approver details.
        """
        approval = db.session.query(DataSourceApproval).filter_by(id=approval_id).first()
        if approval:
            approval.status = new_status
            approval.approved_date = db.func.now() if new_status in ["Approved", "Declined"] else None
            approver = models.User.query.get(approver_id)
            if approver:
                approval.approver_name = approver.name
                approval.approver_email = approver.email
            db.session.commit()
        return approval

# File: handlers/my_approvals.py
from flask import jsonify
from redash.handlers.base import BaseResource
from redash.models import DataSourceApproval, User, Group, Project
from sqlalchemy.exc import SQLAlchemyError


class MyApprovalsResource(BaseResource):
    def get(self):
        """
        Fetch approvals for the current user filtered by status 'Pending'.
        Includes additional fields for owner, group, and project details.
        """
        current_user = self.current_user

        try:
            # Filter approvals for the current user with status 'Pending'
            approvals = DataSourceApproval.query.filter(
                (DataSourceApproval.group_owner_id == current_user.id) |
                (DataSourceApproval.project_owner_id == current_user.id),
                DataSourceApproval.status == "Pending"
            ).all()
        except SQLAlchemyError as e:
            return jsonify({"error": "Database error: {}".format(str(e))}), 500

        # Fetch user details for requester and data source owner
        user_ids = list(set(
            [approval.data_source_owner_id for approval in approvals] +
            [approval.requester_id for approval in approvals if approval.requester_id]
        ))

        user_map = {
            user.id: {"name": user.name, "email": user.email}
            for user in User.query.filter(User.id.in_(user_ids)).all()
        }

        # Fetch group and project details
        group_ids = [approval.group_id for approval in approvals if approval.group_id]
        project_ids = [approval.project_id for approval in approvals if approval.project_id]

        group_map = {
            group.id: group.name for group in Group.query.filter(Group.id.in_(group_ids)).all()
        }
        project_map = {
            project.id: project.name for project in Project.query.filter(Project.id.in_(project_ids)).all()
        }

        # Build the response
        results = []
        for approval in approvals:
            results.append({
                "approval_id": approval.id,
                "comments": approval.comments,
                "data_source_name": approval.data_source.name if approval.data_source else "N/A",
                "group_name": group_map.get(approval.group_id, "N/A"),
                "project_name": project_map.get(approval.project_id, "N/A"),
                "status": approval.status,
                "requester_name": user_map.get(approval.requester_id, {}).get("name", "N/A"),
                "requester_email": user_map.get(approval.requester_id, {}).get("email", "N/A"),
                "data_source_owner_name": user_map.get(approval.data_source_owner_id, {}).get("name", "N/A"),
                "created_date": approval.created_date,
                "approval_type": approval.approval_type,                
                "approved_date": approval.approved_date,
            })

        return jsonify(results)


class MyRequestsResource(BaseResource):
    def get(self):
        """
        Fetch requests made by the current user without filtering by status.
        Includes additional fields for requester, group, and project details.
        """
        current_user = self.current_user

        try:
            # Filter requests by requester_id matching current_user.id
            requests = DataSourceApproval.query.filter(
                DataSourceApproval.requester_id == current_user.id
            ).all()
        except SQLAlchemyError as e:
            return jsonify({"error": "Database error: {}".format(str(e))}), 500

        # Fetch user details for data source owner
        user_ids = list(set(
            [request.data_source_owner_id for request in requests]
        ))

        user_map = {
            user.id: {"name": user.name, "email": user.email}
            for user in User.query.filter(User.id.in_(user_ids)).all()
        }

        # Fetch group and project details
        group_ids = [request.group_id for request in requests if request.group_id]
        project_ids = [request.project_id for request in requests if request.project_id]

        group_map = {
            group.id: group.name for group in Group.query.filter(Group.id.in_(group_ids)).all()
        }
        project_map = {
            project.id: project.name for project in Project.query.filter(Project.id.in_(project_ids)).all()
        }

        # Build the response
        results = []
        for request in requests:
            results.append({
                "request_id": request.id,
                "approval_type": request.approval_type,                
                "comments": request.comments,
                "data_source_name": request.data_source.name if request.data_source else "N/A",
                "group_name": group_map.get(request.group_id, "N/A"),
                "project_name": project_map.get(request.project_id, "N/A"),
                "status": request.status,
                "requester_name": user_map.get(request.requester_id, {}).get("name", "N/A"),
                "requester_email": user_map.get(request.requester_id, {}).get("email", "N/A"),
                "approver_name": request.approver_name,                
                "created_date": request.created_date,
                "approved_date": request.approved_date,
            })

        return jsonify(results)

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from gestion_magasin_backend.utils import CustomPagination
from notification.models import Notification, NotificationPreference
from notification.serializers import (
    NotificationPreferenceSerializer,
    NotificationSerializer,
)


class NotificationPreferenceView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request):
        pref, _ = NotificationPreference.objects.get_or_create(user=request.user)
        return Response(NotificationPreferenceSerializer(pref).data, status=status.HTTP_200_OK)

    @staticmethod
    def put(request):
        pref, _ = NotificationPreference.objects.get_or_create(user=request.user)
        serializer = NotificationPreferenceSerializer(pref, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class NotificationListView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request):
        qs = Notification.objects.filter(user=request.user).select_related("store", "product")
        paginator = CustomPagination()
        paginator.page_size = 10
        page = paginator.paginate_queryset(qs, request)
        serializer = NotificationSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class NotificationMarkReadView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def post(request):
        ids = request.data.get("ids")
        qs = Notification.objects.filter(user=request.user, is_read=False)
        if ids:
            qs = qs.filter(id__in=ids)
        updated = qs.update(is_read=True)
        return Response({"updated": updated}, status=status.HTTP_200_OK)


class NotificationUnreadCountView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request):
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return Response({"count": count}, status=status.HTTP_200_OK)


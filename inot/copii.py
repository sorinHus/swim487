"""Copiii părinților: listă, adăugare, editare, ștergere."""
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Copil, Programare


class CopilSerializer(serializers.Serializer):
    nume = serializers.CharField(max_length=100)
    varsta = serializers.IntegerField(min_value=3, max_value=18)
    avansat = serializers.BooleanField(default=False)


def viitoare(copil):
    azi = timezone.localtime(timezone.now()).date()
    return copil.programari.filter(data__gte=azi, status='confirmat')


def ser_copil(c):
    return {'id': c.id, 'nume': c.nume, 'varsta': c.varsta, 'avansat': c.avansat, 'grupa': c.grupa,
            'viitoare': viitoare(c).count()}


def exista_nume(user, nume, exclude_id=None):
    qs = Copil.objects.filter(user=user, nume__iexact=nume.strip())
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs.exists()


class CopiiView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response([ser_copil(c) for c in request.user.copii.all()])

    def post(self, request):
        ser = CopilSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        if exista_nume(request.user, d['nume']):
            raise ValidationError({'detail': 'Ai deja un copil cu acest nume.'})
        c = Copil.objects.create(user=request.user, nume=d['nume'].strip(), varsta=d['varsta'], avansat=d['avansat'])
        return Response(ser_copil(c), status=status.HTTP_201_CREATED)


class CopilView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, pk):
        try:
            return Copil.objects.get(pk=pk, user=request.user)
        except Copil.DoesNotExist:
            raise NotFound('Copilul nu există.')

    def patch(self, request, pk):
        """Vârsta și nivelul se aplică programărilor noi; la cele viitoare se actualizează doar numele."""
        c = self._get(request, pk)
        ser = CopilSerializer(data={**{'nume': c.nume, 'varsta': c.varsta, 'avansat': c.avansat}, **request.data})
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        if exista_nume(request.user, d['nume'], exclude_id=c.pk):
            raise ValidationError({'detail': 'Ai deja un copil cu acest nume.'})
        with transaction.atomic():
            c.nume, c.varsta, c.avansat = d['nume'].strip(), d['varsta'], d['avansat']
            c.save()
            viitoare(c).update(nume_copil=c.nume)
        return Response(ser_copil(c))

    def delete(self, request, pk):
        c = self._get(request, pk)
        if viitoare(c).exists():
            raise ValidationError({'detail': 'Copilul are programări viitoare active. Anulează-le întâi.'})
        c.delete()  # programările vechi rămân în istoric
        return Response(status=status.HTTP_204_NO_CONTENT)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class JobItem:
    """Representa una oferta de empleo unificada en el sistema.
    
    Attributes:
        id (str): Identificador único de la oferta.
        title (str): Título del puesto de trabajo.
        company (str): Nombre de la empresa que oferta el puesto.
        location (str): Ubicación geográfica del puesto.
        url (str): Enlace a la oferta original.
        source (str): Origen de los datos (ej. 'linkedin', 'infojobs').
        posted_within_1h (bool): Indica si la oferta fue publicada hace menos de una hora.
        description (str): Descripción detallada de la oferta.
        published_at (str): Fecha o texto de publicación.
        aliases (tuple[str, ...]): Otros identificadores o alias.
        features (dict[str, Any]): Características extraídas (salario, tecnologías, etc.).
    """
    # Identificadores principales y detalles básicos de la oferta
    id: str
    title: str
    company: str
    location: str
    url: str
    source: str
    
    # Metadatos adicionales de la oferta, con valores por defecto
    posted_within_1h: bool = False
    description: str = ""
    published_at: str = ""
    aliases: tuple[str, ...] = ()
    
    # Campo flexible para almacenar atributos adicionales usando un default_factory
    features: dict[str, Any] = field(default_factory=dict)


class JobProvider(Protocol):
    """Interfaz estándar (Protocol) para los proveedores de ofertas de empleo (scrapers).
    
    Define el contrato que deben seguir todos los scrapers de ofertas
    para asegurar compatibilidad con el sistema central.
    
    Attributes:
        source (str): Identificador único del proveedor.
    """
    source: str

    def fetch_jobs(self) -> list[JobItem]:
        """Extrae y devuelve una lista de ofertas de trabajo de la fuente correspondiente.

        Returns:
            list[JobItem]: Lista de ofertas de trabajo procesadas y estructuradas según el modelo JobItem.
        """
        ...
        
    def check_session(self) -> tuple[bool, str]:
        """Comprueba el estado de la sesión o conexión con el proveedor.
        
        Útil para detectar si las cookies o tokens han expirado antes de intentar
        extraer los datos.

        Returns:
            tuple[bool, str]: Un par (estado, mensaje) que contiene:
                - bool: True si la sesión es válida, False en caso contrario.
                - str: Mensaje descriptivo sobre el estado de la sesión.
        """
        ...

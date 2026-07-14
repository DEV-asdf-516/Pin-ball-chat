from fastapi import APIRouter

from domain.catalog.reader import list_catalog_by_kind
from domain.catalog.specs import CatalogKind
from domain.plots import get_plot
from domain.catalog.writer import create_catalog_item, delete_catalog_item, update_catalog_item
from server.dependencies import DbConn
from server.specs import CatalogDeleteResponse, PlotCreateRequest, PlotResponse, PlotsPageResponse, PlotUpdateRequest

router = APIRouter()


@router.get("/api/plots", response_model=PlotsPageResponse)
def get_plots(conn: DbConn, before: int | None = None, limit: int = 100):
    page = list_catalog_by_kind(conn, CatalogKind.PLOT, before, limit)
    return {
        "plots": page["items"], 
        "nextCursor": page["nextCursor"], 
        "hasMore": page["hasMore"]
    }


@router.get("/api/plots/{plot_id}", response_model=PlotResponse)
def get_plot_route(plot_id: str, conn: DbConn):
    return get_plot(conn, plot_id)


@router.post("/api/plots", response_model=PlotResponse)
def post_plot(conn: DbConn, body: PlotCreateRequest):
    return create_catalog_item(conn, CatalogKind.PLOT, body.to_dict())


@router.put("/api/plots/{plot_id}", response_model=PlotResponse)
def put_plot(plot_id: str, conn: DbConn, body: PlotUpdateRequest):
    return update_catalog_item(conn, CatalogKind.PLOT, plot_id, body.to_dict())


@router.delete("/api/plots/{plot_id}", response_model=CatalogDeleteResponse)
def delete_plot(plot_id: str, conn: DbConn):
    return delete_catalog_item(conn, CatalogKind.PLOT, plot_id)

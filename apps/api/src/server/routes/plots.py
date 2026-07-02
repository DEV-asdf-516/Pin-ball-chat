from fastapi import APIRouter

from domain.content.reader import find_all_content
from domain.content.specs import ContentKind
from domain.plots import get_plot
from domain.content.writer import create_content_item, delete_content_item, update_content_item
from server.dependencies import DbConn
from server.schemas import PlotCreateRequest, PlotUpdateRequest

router = APIRouter()


@router.get("/api/plots")
def get_plots(conn: DbConn):
    return find_all_content(conn, ContentKind.PLOT)


@router.get("/api/plots/{plot_id}")
def get_plot_route(plot_id: str, conn: DbConn):
    return get_plot(conn, plot_id)


@router.post("/api/plots")
def post_plot(conn: DbConn, body: PlotCreateRequest):
    return create_content_item(conn, ContentKind.PLOT, body.to_dict())


@router.put("/api/plots/{plot_id}")
def put_plot(plot_id: str, conn: DbConn, body: PlotUpdateRequest):
    return update_content_item(conn, ContentKind.PLOT, plot_id, body.to_dict())


@router.delete("/api/plots/{plot_id}")
def delete_plot(plot_id: str, conn: DbConn):
    return delete_content_item(conn, ContentKind.PLOT, plot_id)

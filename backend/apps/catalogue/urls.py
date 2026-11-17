from django.urls import path

from . import views

urlpatterns = [
    path("categories/", views.CategoryListView.as_view(), name="categories"),
    path("products/", views.ProductListView.as_view(), name="products"),
    path("products/<slug:slug>/", views.ProductDetailView.as_view(), name="product-detail"),
    path("manage/categories/", views.ManageCategoryCreateView.as_view(), name="manage-category-create"),
    path("manage/products/", views.ManageProductCreateView.as_view(), name="manage-product-create"),
    path("manage/products/<str:product_id>/", views.ManageProductDetailView.as_view(), name="manage-product-detail"),
]

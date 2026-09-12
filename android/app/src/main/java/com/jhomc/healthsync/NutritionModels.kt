package com.jhomc.healthsync

/** Los 9 nutrientes en el orden canónico del servidor (NUTRIENT_FIELDS). */
val NUTRIENT_FIELDS = listOf(
    "kcal",
    "carbohidratos",
    "fibra",
    "proteina",
    "grasa",
    "hierro",
    "calcio",
    "vitamina_c",
    "vitamina_a",
)

data class FoodEntry(
    val orden: Int,
    val alimento: String,
    val cantidadG: Double?,
    val nutrients: Map<String, Double?>,
)

data class NutritionParams(
    val pesoKg: Double,
    val factorProteina: Double,
    val factorGrasa: Double,
    val kcalObjetivo: Double,
)

data class NutritionDay(
    val fecha: String,
    val hasData: Boolean,
    val prefilled: Boolean,
    val prefillSource: String?,
    val entradas: List<FoodEntry>,
    val consumido: Map<String, Double>,
    val objetivo: Map<String, Double>,
    val parametros: NutritionParams,
)

/** Fila del editor: lo que el usuario teclea antes de guardar. */
data class FoodDraft(
    val alimento: String,
    val cantidadG: String,
)

data class FoodItem(
    val nombre: String,
    val categoria: String,
    val nutrients: Map<String, Double?>,
)

data class NutrientLabel(
    val name: String,
    val label: String,
)

data class FoodsData(
    val items: List<FoodItem>,
    val nutrientLabels: List<NutrientLabel>,
)

data class MealTemplate(
    val id: Int,
    val nombre: String,
    val alimentos: List<FoodDraft>,
)

package com.jhomc.healthsync

import androidx.health.connect.client.records.MealType
import androidx.health.connect.client.records.NutritionRecord
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.units.Energy
import androidx.health.connect.client.units.Mass
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * Mapeo puro `NutritionDay (servidor) -> List<NutritionRecord> (Health Connect)`.
 *
 * Contrato en `docs/architecture/nutrition-write-contract.md`:
 * - 1 registro por alimento (entrada del diario), nunca agregado diario.
 * - Unidades hoja (mg/µg) convertidas a gramos HC; ceros/nulos se omiten.
 * - `clientRecordId` estable `gym-diario-<fecha>-<orden>` + `clientRecordVersion`
 *   = hash del contenido: re-insert = upsert, sin borrar+crear.
 * - Hora = fecha del diario, a las 12:00 en la zona local (ventana de 1 min).
 *   Para hoy se recorta a `now` si todavía no son las 12:00. La hora exacta de
 *   ingesta no existe, pero conservar el día evita sumar el histórico en hoy.
 *   `mealType` siempre UNKNOWN.
 *
 * Sin I/O, sin Android framework (salvo java.time): testeable en JVM.
 */
object NutritionPublishMapper {

    const val CLIENT_ID_PREFIX = "gym-diario"
    const val DURATION_SECONDS = 60L
    const val MAX_NAME_CHARS = 100
    const val TIME_POLICY_VERSION = 2L

    data class MappedMeal(
        val record: NutritionRecord,
        val clientRecordId: String,
        val clientRecordVersion: Long,
    )

    fun clientRecordId(fecha: String, orden: Int): String =
        "$CLIENT_ID_PREFIX-$fecha-$orden"

    /** Hash estable del contenido (≥1): alimenta clientRecordVersion. */
    fun contentVersion(entry: FoodEntry): Long {
        val parts = buildString {
            append(TIME_POLICY_VERSION)
            append('|')
            append(entry.alimento.trim().lowercase())
            append('|')
            append(entry.cantidadG?.toString() ?: "")
            append('|')
            for (f in NUTRIENT_FIELDS) {
                append(entry.nutrients[f]?.toString() ?: "")
                append('|')
            }
        }
        val h = parts.hashCode().toLong() and 0x7fffffffL
        // The old policy used values in [1, Int.MAX_VALUE]. Keep the new
        // policy strictly above that range so Health Connect upserts the same
        // clientRecordId and moves the record to its correct calendar date.
        return 3_000_000_000L + h
    }

    fun displayName(entry: FoodEntry): String {
        val base = entry.alimento.trim()
        val qty = entry.cantidadG
        val name = if (qty != null && qty.isFinite() && qty > 0) {
            val qtyText = if (qty % 1.0 == 0.0) qty.toLong().toString() else qty.toString()
            "$base ($qtyText g)"
        } else {
            base
        }
        return if (name.length <= MAX_NAME_CHARS) name else name.take(MAX_NAME_CHARS)
    }

    private fun massInRange(grams: Double, maxGrams: Double): Mass? {
        if (!grams.isFinite() || grams <= 0.0 || grams > maxGrams) return null
        return Mass.grams(grams)
    }

    private fun energyInRange(kcal: Double): Energy? {
        if (!kcal.isFinite() || kcal <= 0.0 || kcal > 100_000.0) return null
        return Energy.kilocalories(kcal)
    }

    /**
     * Mapea un día completo. Entradas sin nutrientes válidos se omiten
     * (HC rechazaría el lote entero si coláramos un campo fuera de rango:
     * aquí se omite el campo, y si no queda nada, la fila).
     * Todas las filas usan la fecha del diario a mediodía local. Para el día
     * actual, si mediodía aún es futuro, se usa `now`.
     */
    fun mapDay(
        day: NutritionDay,
        zoneId: ZoneId = ZoneId.systemDefault(),
        now: Instant = Instant.now(),
    ): List<MappedMeal> {
        val fecha = runCatching { LocalDate.parse(day.fecha) }.getOrNull() ?: return emptyList()
        val entries = day.entradas.sortedBy { it.orden }
        if (entries.isEmpty()) return emptyList()
        return entries.mapNotNull { entry ->
            mapEntry(fecha, entry, zoneId, now)
        }
    }

    internal fun mapEntry(
        fecha: LocalDate,
        entry: FoodEntry,
        zoneId: ZoneId,
        now: Instant = Instant.now(),
    ): MappedMeal? {
        val nutrients = entry.nutrients
        fun num(key: String): Double? {
            val v = nutrients[key] ?: return null
            return if (v.isFinite() && v > 0.0) v else null
        }

        val energy = num("kcal")?.let { energyInRange(it) }
        val protein = num("proteina")?.let { massInRange(it, 100_000.0) }
        val carbs = num("carbohidratos")?.let { massInRange(it, 100_000.0) }
        val fat = num("grasa")?.let { massInRange(it, 100_000.0) }
        val fiber = num("fibra")?.let { massInRange(it, 100_000.0) }
        // Hoja en mg → HC en g.
        val calcium = num("calcio")?.let { massInRange(it / 1_000.0, 100.0) }
        val iron = num("hierro")?.let { massInRange(it / 1_000.0, 100.0) }
        val vitaminC = num("vitamina_c")?.let { massInRange(it / 1_000.0, 100.0) }
        // Hoja en µg → HC en g.
        val vitaminA = num("vitamina_a")?.let { massInRange(it / 1_000_000.0, 100.0) }

        if (energy == null && protein == null && carbs == null && fat == null &&
            fiber == null && calcium == null && iron == null &&
            vitaminC == null && vitaminA == null
        ) {
            return null
        }

        val zoneRules = zoneId.rules
        val datedNoon = fecha.atTime(12, 0).atZone(zoneId).toInstant()
        val endInstant = minOf(datedNoon, now)
        val startInstant = endInstant.minusSeconds(DURATION_SECONDS)
        if (!startInstant.isBefore(endInstant)) return null
        val startOffset = zoneRules.getOffset(startInstant)
        val endOffset = zoneRules.getOffset(endInstant)

        val clientId = clientRecordId(fecha.toString(), entry.orden)
        val version = contentVersion(entry)
        val metadata = Metadata.manualEntry(clientId, version)

        val record = NutritionRecord(
            startTime = startInstant,
            startZoneOffset = startOffset,
            endTime = endInstant,
            endZoneOffset = endOffset,
            metadata = metadata,
            energy = energy,
            protein = protein,
            totalCarbohydrate = carbs,
            totalFat = fat,
            dietaryFiber = fiber,
            calcium = calcium,
            iron = iron,
            vitaminC = vitaminC,
            vitaminA = vitaminA,
            name = displayName(entry).takeIf { it.isNotBlank() },
            mealType = MealType.MEAL_TYPE_UNKNOWN,
        )
        return MappedMeal(record, clientId, version)
    }

    /** Hash del día publicado (para reconciliación: servidor vs HC). */
    fun dayHash(day: NutritionDay): String {
        val parts = day.entradas.sortedBy { it.orden }.joinToString(";") { e ->
            val nuts = NUTRIENT_FIELDS.joinToString(",") { f -> e.nutrients[f]?.toString() ?: "" }
            "${e.orden}|${e.alimento.trim().lowercase()}|${e.cantidadG}|$nuts"
        }
        return "v$TIME_POLICY_VERSION-${parts.hashCode().toString(36)}"
    }
}

package com.jhomc.healthsync

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Contrato cliente de la API v1 (training-api-contract.md §2-§3).
 * El servidor Python cubre el otro lado en tests/test_training_api.py.
 */
class TrainingApiClientTest {

    private val client = TrainingApiClient()

    private fun sessionBody(fecha: String = "2026-09-07", hasData: Boolean = true): String {
        val sets = if (hasData) {
            """[{"set_orden":1,"ejercicio":"Press","kg":80.0,"reps":8.0,"rir":1.0,"descanso_seg":null,"rm":103.9}]"""
        } else {
            "[]"
        }
        return """{"schema_version":1,"fecha":"$fecha","semana":19,"dia":"LUNES","has_data":$hasData,"sets":$sets}"""
    }

    @Test
    fun `resolveApiBase prefiere el override explicito`() {
        val res = TrainingApiClient.resolveApiBase(
            "http://192.168.1.6:8000/sync/health-connect",
            "http://192.168.1.99:8000/",
        )
        assertEquals("http://192.168.1.99:8000", res.getOrThrow())
    }

    @Test
    fun `resolveApiBase recorta el sufijo exacto de sync`() {
        val res = TrainingApiClient.resolveApiBase("http://192.168.1.6:8000/sync/health-connect")
        assertEquals("http://192.168.1.6:8000", res.getOrThrow())
    }

    @Test
    fun `resolveApiBase falla sin base conocida`() {
        assertTrue(TrainingApiClient.resolveApiBase("").isFailure)
        assertTrue(TrainingApiClient.resolveApiBase("http://host:8000/otro-path").isFailure)
    }

    @Test
    fun `get session parsea sets con rm`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody(sessionBody()))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.getSession(base, "secret", "2026-09-07")
            assertTrue(res is TrainingResult.Ok)
            val session = (res as TrainingResult.Ok).value
            assertEquals("2026-09-07", session.fecha)
            assertEquals(19, session.semana)
            assertEquals("LUNES", session.dia)
            assertTrue(session.hasData)
            assertEquals(1, session.sets.size)
            assertEquals(103.9, session.sets[0].rm!!, 0.001)
            val recorded = server.takeRequest()
            assertEquals("/api/v1/sesion?fecha=2026-09-07", recorded.path)
            assertEquals("secret", recorded.getHeader("X-Sync-Token"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `get dia vacio`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody(sessionBody(hasData = false)))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.getSession(base, "secret", "2026-09-07")
            val session = (res as TrainingResult.Ok).value
            assertTrue(!session.hasData)
            assertTrue(session.sets.isEmpty())
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `401 es ApiError permanente y 500 NetworkError`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Token inválido"}"""))
        server.enqueue(MockResponse().setResponseCode(500).setBody("boom"))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val auth = client.getSession(base, "wrong", "2026-09-07")
            assertTrue(auth is TrainingResult.ApiError)
            assertEquals(401, (auth as TrainingResult.ApiError).status)
            assertEquals("Token inválido", auth.detail)
            val down = client.getSession(base, "secret", "2026-09-07")
            assertTrue(down is TrainingResult.NetworkError)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `save envia fecha y sets y parsea lo guardado`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody(sessionBody()))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.saveSession(
                base, "secret", "2026-09-07",
                listOf(TrainingSetDraft("Press", "80", "8", "1", "")),
            )
            assertTrue(res is TrainingResult.Ok)
            val recorded = server.takeRequest()
            assertEquals("/api/v1/sesion", recorded.path)
            val body = recorded.body.readUtf8()
            assertTrue(body.contains("\"fecha\":\"2026-09-07\""))
            assertTrue(body.contains("\"ejercicio\":\"Press\""))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `save vacio se rechaza en cliente`() {
        val res = client.saveSession("http://x", "s", "2026-09-07", emptyList())
        assertTrue(res is TrainingResult.ApiError)
    }

    @Test
    fun `delete usa query de fecha`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"schema_version":1,"fecha":"2026-09-07","deleted":true}"""))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.deleteSession(base, "secret", "2026-09-07")
            assertTrue(res is TrainingResult.Ok)
            assertEquals("/api/v1/sesion?fecha=2026-09-07", server.takeRequest().path)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `catalogo parsea grupo y categoria`() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"schema_version":1,"count":1,"ejercicios":[{"ejercicio":"Press","grupo_muscular":"Pectoral","categoria":"EMPUJE"}]}""",
            ),
        )
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.getCatalog(base, "secret")
            val data = (res as TrainingResult.Ok).value
            val items = data.exercises
            assertEquals(1, items.size)
            assertEquals("Pectoral", items[0].grupoMuscular)
            assertEquals("EMPUJE", items[0].categoria)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `schema_version futura se rechaza`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody(sessionBody().replace("\"schema_version\":1", "\"schema_version\":99")))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.getSession(base, "secret", "2026-09-07")
            assertTrue(res is TrainingResult.ApiError)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `templates lista parsea ejercicios`() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"schema_version":1,"count":1,"plantillas":[{"id":7,"nombre":"Tiron","clasificacion":"JALON","ejercicios":["Remo","Press"]}]}""",
            ),
        )
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.getTemplates(base, "secret")
            val items = (res as TrainingResult.Ok).value
            assertEquals(1, items.size)
            assertEquals(7, items[0].id)
            assertEquals(listOf("Remo", "Press"), items[0].ejercicios)
            assertEquals("/api/v1/plantillas", server.takeRequest().path)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `apply envia id y fecha y parsea preview`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"plantilla_id":7,"fecha":"2026-09-07","semana":19,"dia":"LUNES","sets":[{"set_orden":1,"ejercicio":"Remo","kg":60.0,"reps":10.0,"rir":2.0,"descanso_seg":90.0,"rm":null}]}""",
        ))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.applyTemplate(base, "secret", 7, "2026-09-07")
            val session = (res as TrainingResult.Ok).value
            assertEquals("2026-09-07", session.fecha)
            assertEquals("Remo", session.sets[0].ejercicio)
            val recorded = server.takeRequest()
            assertEquals("/api/v1/plantilla/aplicar", recorded.path)
            assertTrue(recorded.body.readUtf8().contains("\"plantilla_id\":7"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `apply inexistente es 404 permanente`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(404).setBody("""{"detail":"La plantilla no existe."}"""))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.applyTemplate(base, "secret", 999, "2026-09-07")
            assertTrue(res is TrainingResult.ApiError)
            assertEquals(404, (res as TrainingResult.ApiError).status)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `saveTemplate y createExercise`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"plantilla":{"id":3,"nombre":"Empuje","clasificacion":"EMPUJE","ejercicios":["Press"],"updated":false}}""",
        ))
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"ejercicio":{"ejercicio":"Sentadilla","grupo_muscular":"Cuadriceps","categoria":"PIERNA"}}""",
        ))
        server.enqueue(MockResponse().setResponseCode(409).setBody("""{"detail":"El ejercicio 'X' ya existe en el catálogo."}"""))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val saved = client.saveTemplate(base, "secret", "Empuje", listOf("Press"))
            assertEquals("Empuje", (saved as TrainingResult.Ok).value.nombre)
            assertEquals("/api/v1/plantilla/guardar", server.takeRequest().path)
            val created = client.createExercise(base, "secret", "Sentadilla", "Cuadriceps", "PIERNA")
            assertTrue(created is TrainingResult.Ok)
            assertEquals("/api/v1/ejercicio", server.takeRequest().path)
            val dup = client.createExercise(base, "secret", "X", "Y", "EMPUJE")
            assertTrue(dup is TrainingResult.ApiError)
            assertEquals(409, (dup as TrainingResult.ApiError).status)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `undo peek y undo`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"kind":"sesion","fecha_iso":"2026-09-07"}""",
        ))
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"kind":"sesion","fecha_iso":"2026-09-07","has_data":false}""",
        ))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val peek = client.undoPeek(base, "secret")
            assertEquals("sesion", (peek as TrainingResult.Ok).value.kind)
            assertEquals("2026-09-07", peek.value.fechaIso)
            assertEquals("/api/v1/undo/peek", server.takeRequest().path)
            val undone = client.undo(base, "secret", "2026-09-07")
            assertEquals(false, (undone as TrainingResult.Ok).value.hasData)
            assertEquals("/api/v1/undo", server.takeRequest().path)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `catalogo con meta categorias`() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"schema_version":1,"count":0,"ejercicios":[],"meta":{"categorias":[{"name":"EMPUJE","muscles":["Pectoral"]}]}}""",
            ),
        )
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.getCatalog(base, "secret")
            val data = (res as TrainingResult.Ok).value
            assertEquals(1, data.categories.size)
            assertEquals(listOf("Pectoral"), data.categories[0].muscles)
        } finally {
            server.shutdown()
        }
    }

    private fun nutritionDayBody(): String = """{"schema_version":1,"fecha":"2026-09-07","has_data":true,"prefilled":false,"prefill_source":null,"entradas":[{"orden":1,"alimento":"Avena","cantidad_g":50.0,"kcal":195.0,"carbohidratos":34.0,"fibra":5.0,"proteina":9.0,"grasa":3.0,"hierro":2.0,"calcio":27.0,"vitamina_c":0.0,"vitamina_a":0.0}],"consumido":{"kcal":195.0,"carbohidratos":34.0,"fibra":5.0,"proteina":9.0,"grasa":3.0,"hierro":2.0,"calcio":27.0,"vitamina_c":0.0,"vitamina_a":0.0,"cantidad_g":50.0},"objetivo":{"kcal":2300.0,"carbohidratos":297.0,"fibra":0.0,"proteina":105.0,"grasa":77.0,"hierro":0.0,"calcio":0.0,"vitamina_c":0.0,"vitamina_a":0.0},"parametros":{"peso_kg":70.0,"factor_proteina":1.5,"factor_grasa":1.1,"kcal_objetivo":2300.0}}"""

    @Test
    fun `nutrition day parsea entradas objetivo y parametros`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody(nutritionDayBody()))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.getNutritionDay(base, "secret", "2026-09-07")
            val day = (res as TrainingResult.Ok).value
            assertEquals("2026-09-07", day.fecha)
            assertTrue(day.hasData)
            assertEquals(1, day.entradas.size)
            assertEquals(195.0, day.entradas[0].nutrients["kcal"]!!, 0.001)
            assertEquals(195.0, day.consumido["kcal"]!!, 0.001)
            assertEquals(105.0, day.objetivo["proteina"]!!, 0.001)
            assertEquals(70.0, day.parametros.pesoKg, 0.001)
            assertEquals("/api/v1/diario?fecha=2026-09-07", server.takeRequest().path)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `nutrition save envia entradas y params`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody(nutritionDayBody()))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.saveNutritionDay(
                base, "secret", "2026-09-07",
                listOf(FoodDraft("Avena", "50")),
                NutritionParams(80.0, 2.0, 1.0, 2500.0),
            )
            assertTrue(res is TrainingResult.Ok)
            val recorded = server.takeRequest()
            assertEquals("/api/v1/diario", recorded.path)
            val body = recorded.body.readUtf8()
            assertTrue(body.contains("\"peso_kg\":80"))
            assertTrue(body.contains("\"alimento\":\"Avena\""))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `nutrition save vacio se rechaza en cliente`() {
        val res = client.saveNutritionDay("http://x", "s", "2026-09-07", emptyList(), null)
        assertTrue(res is TrainingResult.ApiError)
    }

    @Test
    fun `foods parsea items y etiquetas`() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"schema_version":1,"count":1,"alimentos":[{"nombre":"Avena","categoria":"Cereal","kcal":389.0,"carbohidratos":68.0,"fibra":10.0,"proteina":17.0,"grasa":6.9,"hierro":4.2,"calcio":54.0,"vitamina_c":0.0,"vitamina_a":0.0}],"meta":{"nutrientes":[{"name":"kcal","label":"kcal"},{"name":"proteina","label":"Prot (g)"}]}}""",
            ),
        )
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.getFoods(base, "secret")
            val data = (res as TrainingResult.Ok).value
            assertEquals("Avena", data.items[0].nombre)
            assertEquals(389.0, data.items[0].nutrients["kcal"]!!, 0.001)
            assertEquals("Prot (g)", data.nutrientLabels.first { it.name == "proteina" }.label)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `meal templates aplicar y guardar`() {        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"count":1,"plantillas":[{"id":2,"nombre":"Desayuno","alimentos":[{"alimento":"Avena","cantidad_g":100.0}]}]}""",
        ))
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"plantilla_id":2,"fecha":"2026-09-07","entradas":[{"orden":1,"alimento":"Avena","cantidad_g":100.0,"kcal":389.0,"carbohidratos":68.0,"fibra":10.0,"proteina":17.0,"grasa":6.9,"hierro":4.2,"calcio":54.0,"vitamina_c":0.0,"vitamina_a":0.0}]}""",
        ))
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"plantilla":{"id":2,"nombre":"Desayuno","updated":true}}""",
        ))
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"alimento":{"nombre":"Huevo","categoria":"Proteina"}}""",
        ))
        server.enqueue(MockResponse().setResponseCode(409).setBody("""{"detail":"El alimento 'Huevo' ya existe en el catálogo"}"""))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val listed = client.getMealTemplates(base, "secret")
            assertEquals("Desayuno", (listed as TrainingResult.Ok).value[0].nombre)
            val preview = client.applyMealTemplate(base, "secret", 2, "2026-09-07")
            assertEquals(389.0, (preview as TrainingResult.Ok).value[0].nutrients["kcal"]!!, 0.001)
            val saved = client.saveMealTemplate(base, "secret", "Desayuno", listOf(FoodDraft("Avena", "100")))
            assertEquals(2, (saved as TrainingResult.Ok).value.id)
            val created = client.createFood(base, "secret", "Huevo", "Proteina", mapOf("kcal" to 155.0))
            assertTrue(created is TrainingResult.Ok)
            val dup = client.createFood(base, "secret", "Huevo", "Proteina", mapOf("kcal" to 155.0))
            assertTrue(dup is TrainingResult.ApiError)
            assertEquals(409, (dup as TrainingResult.ApiError).status)
        } finally {
            server.shutdown()
        }
    }
}

class TrainingSuggestionClientTest {

    private val client = TrainingApiClient()

    @Test
    fun `sugerencia rutina parsea sets con fuente`() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"schema_version":1,"fecha":"2026-09-09","tipo":"rutina","explicacion":"Te tocaba martes.","split_id":1,"slot_dia":"MARTES","pendiente_desde":"2026-09-07","ejercicios":["Sentadilla"],"sets":[{"ejercicio":"Sentadilla","kg":100.0,"reps":5.0,"rir":2.0,"descanso_seg":null,"fuente_fecha":"2026-09-02"}]}""",
            ),
        )
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.getSuggestion(base, "secret", "2026-09-09")
            val s = (res as TrainingResult.Ok).value
            assertEquals("rutina", s.tipo)
            assertEquals("MARTES", s.slotDia)
            assertEquals("2026-09-07", s.pendienteDesde)
            assertEquals(100.0, s.sets[0].kg!!, 0.001)
            assertEquals("2026-09-02", s.sets[0].fuenteFecha)
            assertEquals("/api/v1/sugerencia?fecha=2026-09-09", server.takeRequest().path)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `sugerencia descanso y nada`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"fecha":"2026-09-10","tipo":"descanso","explicacion":"Hoy toca descanso.","split_id":1,"slot_dia":"MIERCOLES","pendiente_desde":null,"ejercicios":[],"sets":[]}""",
        ))
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"fecha":"2026-09-07","tipo":"nada","explicacion":"El día ya tiene entrenamiento.","split_id":null,"slot_dia":null,"pendiente_desde":null,"ejercicios":[],"sets":[]}""",
        ))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val rest = client.getSuggestion(base, "secret", "2026-09-10")
            assertEquals("descanso", (rest as TrainingResult.Ok).value.tipo)
            val nothing = client.getSuggestion(base, "secret", "2026-09-07")
            assertEquals("nada", (nothing as TrainingResult.Ok).value.tipo)
            assertEquals(null, nothing.value.splitId)
        } finally {
            server.shutdown()
        }
    }
}

class TrainingCardioClientTest {

    private val client = TrainingApiClient()

    @Test
    fun `cardio day parsea sesiones y cuenta`() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"schema_version":1,"fecha":"2026-09-07","count":1,"sesiones":[{"hc_id":"c1","titulo":"Cinta","duracion_min":30.0,"velocidad_kmh":null,"inclinacion_pct":null,"notas":""}]}""",
            ),
        )
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.getCardioDay(base, "secret", "2026-09-07")
            val items = (res as TrainingResult.Ok).value
            assertEquals(1, items.size)
            assertEquals("Cinta", items[0].titulo)
            assertEquals(30.0, items[0].duracionMin, 0.001)
            assertEquals("/api/v1/cardio?fecha=2026-09-07", server.takeRequest().path)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `annotate devuelve deleted`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"hc_id":"c1","deleted":false}""",
        ))
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"hc_id":"c1","deleted":true}""",
        ))
        server.enqueue(MockResponse().setResponseCode(400).setBody("""{"detail":"Sesión de cardio no encontrada."}"""))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val saved = client.annotateCardio(base, "secret", "c1", "10.5", "1", "")
            assertEquals(false, (saved as TrainingResult.Ok).value)
            assertEquals("/api/v1/cardio/anotacion", server.takeRequest().path)
            val deleted = client.annotateCardio(base, "secret", "c1", "", "", "")
            assertEquals(true, (deleted as TrainingResult.Ok).value)
            val missing = client.annotateCardio(base, "secret", "nope", "9", "", "")
            assertTrue(missing is TrainingResult.ApiError)
            assertEquals(400, (missing as TrainingResult.ApiError).status)
        } finally {
            server.shutdown()
        }
    }
}

class TrainingHiitClientTest {

    private val client = TrainingApiClient()

    @Test
    fun `sesion con HIIT parsea velocidad y envia campos`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"fecha":"2026-09-07","semana":19,"dia":"LUNES","has_data":true,"sets":[{"set_orden":1,"ejercicio":"HIIT","kg":null,"reps":null,"rir":null,"descanso_seg":null,"rm":null,"velocidad_kmh":12.3,"dificultad":7.5}],"saved_count":1}""",
        ))
        server.start()
        try {
            val base = "http://${server.hostName}:${server.port}"
            val res = client.saveSession(
                base, "secret", "2026-09-07",
                listOf(TrainingSetDraft("HIIT", "", "", "", "", "12.34", "7.5")),
            )
            val session = (res as TrainingResult.Ok).value
            assertTrue(session.sets[0].isHiit())
            assertEquals(12.3, session.sets[0].velocidadKmh!!, 0.001)
            assertEquals(null, session.sets[0].kg)
            val body = server.takeRequest().body.readUtf8()
            assertTrue(body.contains("\"velocidad_kmh\":12.34"))
            assertTrue(body.contains("\"dificultad\":7.5"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `isHiit ignora caja y espacios`() {
        assertTrue(TrainingSetDraft(" hiit ", "", "", "", "").isHiit())
        assertTrue(!TrainingSetDraft("Press", "80", "8", "1", "").isHiit())
        assertTrue(TrainingSetDraft("", "", "", "", "").isBlank())
        assertTrue(TrainingSetDraft("hiit", "", "", "", "", "12", "7").isBlank().not())
        assertTrue(!TrainingSetDraft("Press", "80", "", "", "").isBlank())
    }
}
